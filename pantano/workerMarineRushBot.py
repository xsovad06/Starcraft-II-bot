import random
from typing import Set, List
from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Difficulty
from sc2.bot_ai import BotAI, Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

class MarineReaperRushBot(BotAI):
    NAME: str = "MarineReaperRushBot"
    RACE: Race = Race.Terran
    
    def __init__(self):
        # Select distance calculation method 0, which is the pure python distance calculation without caching or indexing, using math.hypot()
        self.distance_calculation_method: int = 3
        self.map_width_height_ratio = 0
        self.minute_of_the_game: float = 0
        self.ITERATIONS_PER_MINUTE: int = 165 * 2
        self.MAX_WORKERS:int = 65
        self.MARINE_RANGE: float = 5.0
        self.REAPER_RANGE: float = 5.0
        self.GROUPING_RANGE: int = 10
        self.GROUP_SIZE: int = 10
        self.TH_RANGE: int = 15
        self.MAX_BARRACKS: int = 25
        self.BARRACKS_PER_MINUTE: float = 5.0
        self.priority_enemy_units: List[int] = [UnitTypeId.MEDIVAC, UnitTypeId.SCV, UnitTypeId.SIEGETANKSIEGED]
        self.aggresive_units = {UnitTypeId.MARINE: {'attack': 15, 'defense': 6}, # Marines are primary used for defending TH
                                UnitTypeId.REAPER: {'attack': 13, 'defense': 5}}

    async def incease_attack_defense_group(self, increment: float) -> None:
        """Every minute incease a bit a number of units that can attack and defense to increase effectivnes of the action."""

        if self.minute_of_the_game % 1 == 0:
            for unit in self.aggresive_units:
                self.aggresive_units[unit]['attack'] += increment
                self.aggresive_units[unit]['defense'] += increment

    async def build_workers(self, workers_per_th: int):
        """Train new workers if the count is insufficient."""
        
        count = len(self.townhalls.idle) * workers_per_th
        for th in self.townhalls.idle:
            if (self.can_afford(UnitTypeId.SCV) and
                self.units(UnitTypeId.SCV).amount < self.MAX_WORKERS and
                self.supply_left > 0 and self.supply_workers < count):
                th.train(UnitTypeId.SCV)

    async def workers_defense(self):
        """Workers defend themself if in danger."""

        worker = UnitTypeId.SCV
        enemies: Units = self.enemy_units | self.enemy_structures
        enemies_can_attack: Units = enemies.filter(lambda unit: unit.can_attack_ground and unit.ground_range > 2)
        for w in self.units(worker).idle:
            if await self.unit_attack_executed(w, enemies_can_attack.filter(lambda unit: unit.distance_to(w) < 10), []):
                continue

    async def workers_back_to_work(self):
        """Free workers should return to gather minerals. Chose the closest mineral field with some minerals left."""

        if self.townhalls:
            for w in self.workers.idle:
                mf: Unit = self.mineral_field.closest_to(w)
                if mf.mineral_contents > 100:
                    w.gather(mf)
        # if self.townhalls:
        #     for w in self.workers.idle:
        #         th: Unit = self.townhalls.closest_to(w)
        #         mfs: Units = self.mineral_field.closer_than(10, th)
        #         for mf in mfs:
        #             mf: Unit = mf.closest_to(w)
        #             if mf.mineral_contents > 100:
        #                 w.gather(mf)

    async def build_supplydepots(self, supply_left: int, supply_used: int):
        """Build new supply depot if current depots are used according to the parameters."""

        if (
            self.supply_left < supply_left and self.townhalls and self.supply_used >= supply_used
            and self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.already_pending(UnitTypeId.SUPPLYDEPOT) < 1
        ):
            workers: Units = self.workers.gathering
            if workers:
                worker: Unit = workers.furthest_to(workers.center)
                location: Point2 = await self.find_placement(UnitTypeId.SUPPLYDEPOT, worker.position, placement_step=3)
                if location:
                    worker.build(UnitTypeId.SUPPLYDEPOT, location)
        
        # Lower all depots when finished
        for depot in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
            depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    async def morph_cc_to_orbitalcommand(self):
        """If possible morph the command center to the orbital command."""

        if (
            self.tech_requirement_progress(UnitTypeId.ORBITALCOMMAND) == 1 and
            self.units(UnitTypeId.ORBITALCOMMAND).amount < self.minute_of_the_game / 3 # every 3 minutes can be morphed 1 CC
        ):
            for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
                if self.can_afford(UnitTypeId.ORBITALCOMMAND):
                    cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)

    async def build_factory(self, factory_per_th: int):
        """Build factory from barracks."""

        for th in self.townhalls.idle:
            if (
                self.structures(UnitTypeId.BARRACKS).ready and
                await self.count_builidngs_near_townhall(UnitTypeId.FACTORY, self.TH_RANGE, th.position) < factory_per_th and
                not self.already_pending(UnitTypeId.FACTORY) and self.can_afford(UnitTypeId.FACTORY)
            ):
                workers: Units = self.workers.gathering
                if (workers):
                    worker: Unit = workers.furthest_to(workers.center)
                    location: Point2 = await self.find_placement(UnitTypeId.BARRACKS, th.position, max_distance=self.TH_RANGE, placement_step=3)
                    if location:
                        worker.build(UnitTypeId.FACTORY, location)

    async def expand_to_new_location(self, count: int):
        """Build new command centers until the limit is reached"""

        if (
            1 <= self.townhalls.amount <= count and
            self.townhalls.amount < (self.minute_of_the_game / 2) and # Every 2 minutes of the game can expand
            not self.already_pending(UnitTypeId.COMMANDCENTER) and
            self.can_afford(UnitTypeId.COMMANDCENTER)
        ):
            # The position of the next possible expansion location where you can place a command center
            location: Point2 = await self.get_next_expansion()
            if location:
                worker: Unit = self.select_build_worker(location)
                if worker and self.can_afford(UnitTypeId.COMMANDCENTER):
                    worker.build(UnitTypeId.COMMANDCENTER, location)

    async def build_barracks(self, barracks_per_th: int, max_distance_from_th: int):
        """Build new baracks if can afford and the count not exceeded the parameter value."""

        overall_allowed_barracks_count = min(self.minute_of_the_game * self.BARRACKS_PER_MINUTE, self.MAX_BARRACKS)
        if self.minute_of_the_game % 1 == 0 and (self.minute_of_the_game * self.BARRACKS_PER_MINUTE) < self.MAX_BARRACKS:
            self.BARRACKS_PER_MINUTE -= 0.25 # with every minute decrease the number of barracks per minute to avoi building huge amount of barracks in later minutes of the game.

        for th in self.townhalls.idle:
            barracks_near_th = await self.count_builidngs_near_townhall(UnitTypeId.BARRACKS, self.TH_RANGE, th.position)
            factory_near_th = await self.count_builidngs_near_townhall(UnitTypeId.FACTORY, self.TH_RANGE, th.position)
            if (
                self.tech_requirement_progress(UnitTypeId.BARRACKS) == 1 and
                (barracks_near_th + factory_near_th) < barracks_per_th and
                self.already_pending(UnitTypeId.BARRACKS) <= 1 and
                self.structures(UnitTypeId.BARRACKS).amount < overall_allowed_barracks_count and
                self.can_afford(UnitTypeId.BARRACKS)
            ):
                workers: Units = self.workers.gathering
                if (workers):
                    worker: Unit = workers.closest_to(th)
                    location: Point2 = await self.find_placement(UnitTypeId.BARRACKS, th.position, max_distance=max_distance_from_th, placement_step=3)
                    if location:
                        worker.build(UnitTypeId.BARRACKS, location)

    async def build_refineries(self, refineries_per_th: int, distance_from_cc: int):
        """Build new refinery if can afford and at least one baracks are in counstruction within the distance from cc."""
            
        for th in self.townhalls.idle:
            refineries_near_th = await self.count_builidngs_near_townhall(UnitTypeId.REFINERY, distance_from_cc, th.position)
            if (
                self.structures(UnitTypeId.BARRACKS).ready.amount + self.already_pending(UnitTypeId.BARRACKS) > 0 and
                self.already_pending(UnitTypeId.REFINERY) < 1 and
                refineries_near_th < refineries_per_th and
                self.can_afford(UnitTypeId.REFINERY)
            ):
                vgs: Units = self.vespene_geyser.closer_than(distance_from_cc, th)
                for vg in vgs:
                    if await self.can_place_single(UnitTypeId.REFINERY, vg.position):
                        workers: Units = self.workers.gathering
                        if workers:
                            worker: Unit = workers.closest_to(vg)
                            worker.build_gas(vg)
                            break

    async def train_reapers(self):
        """Make reapers while have enough resources and remaining supply."""

        if self.supply_left > 0:
            for barrack in self.structures(UnitTypeId.BARRACKS).idle:
                if self.can_afford(UnitTypeId.REAPER):
                    barrack.train(UnitTypeId.REAPER)

    async def train_marines(self):
        """Make marines while have enough resources and remaining supply."""

        if self.structures(UnitTypeId.BARRACKS) and self.can_afford(UnitTypeId.MARINE):
            for barrack in self.structures(UnitTypeId.BARRACKS).idle:
                barrack.train(UnitTypeId.MARINE)

    async def group_units_around_th(self) -> None:
        """Gather units by type at the target location."""

        unit_type_ids = [UnitTypeId.MARINE, UnitTypeId.REAPER]
        for th in self.townhalls:
            for unit_type_id in unit_type_ids:
                if self.units(unit_type_id).idle.amount > 2:
                    group_location: Point2 = await self.select_best_grouping_location(
                        th.position,
                        self.GROUPING_RANGE,
                        self.enemy_start_locations[0].position
                    )
                    units_to_group: Units = await self.get_units_group_in_range(th.position, [unit_type_id], self.GROUPING_RANGE)

                    for unit in units_to_group:
                        unit.move(group_location)

    async def group_units_in_action(self) -> None:
        """Try to hold units int he group while executing some action."""

        unit_type_ids = [UnitTypeId.MARINE, UnitTypeId.REAPER]
        if self.units(unit_type_ids[0]).idle.amount + self.units(unit_type_ids[1]).idle.amount > self.GROUP_SIZE:
            unit_position = random.choice(self.units(unit_type_ids[1])).position
            units_to_group: Units = await self.get_units_group_in_range(unit_position, unit_type_ids, self.GROUPING_RANGE)

            for unit in units_to_group:
                unit.move(unit_position)

    async def scann_for_enemies(self) -> None:
        """Find hidden enemies and strutures with scaut unit(reaper)."""

        scauts = []
        if self.units(UnitTypeId.REAPER).idle.amount > 4:
            scauts = random.sample(self.units(UnitTypeId.REAPER).idle, 4)

            patrolling_points = await self.get_patroling_positions_around_map()
            for idx, scaut in enumerate(scauts):
                scaut.patrol(patrolling_points[idx], queue=True)

    async def unit_attack_executed(self, unit: Unit, enemies_in_range: Units, prioritize_units: List[int]) -> bool:
        """Unit is ready to attack, shoot nearest enemy/building."""

        if unit.weapon_cooldown == 0 and enemies_in_range:
            sorted_by_distance = enemies_in_range.sorted(lambda x: x.distance_to(unit))
            if prioritize_units:
                priority_enemy: Units = sorted_by_distance.filter(lambda x: x.type_id in prioritize_units)
                target: Unit = priority_enemy[0] if priority_enemy else sorted_by_distance[0]
            else:
                target: Unit = sorted_by_distance[0]
            unit.attack(target)
            return True
        return False

    async def unit_defend_executed(self, unit: Unit, known_enemies: Units) -> bool:
        """Unit is ready to attack, shoot nearest enemy/building."""

        if unit.weapon_cooldown == 0 and known_enemies:
            closest_enemy: Unit =  known_enemies.sorted(lambda x: x.distance_to(unit))[0]
            unit.attack(closest_enemy)
            return True
        return False
    
    async def reaper_throw_grenade_executed(self, reaper: Unit, enemies_can_attack: Units) -> bool:
        """Attack is on cooldown, if grenade is available throw it to furthest enemy."""

        reaper_grenade_range: float = (self.game_data.abilities[AbilityId.KD8CHARGE_KD8CHARGE.value]._proto.cast_range)
        enemy_ground_units_in_grenade_range: Units = enemies_can_attack.filter(
            lambda unit: not unit.is_structure and not unit.is_flying and unit.type_id not in
            {UnitTypeId.LARVA, UnitTypeId.EGG} and unit.distance_to(reaper) < reaper_grenade_range
        )
        if enemy_ground_units_in_grenade_range and (reaper.is_attacking or reaper.is_moving):
            # If AbilityId.KD8CHARGE_KD8CHARGE in abilities, we check that to see if the reaper grenade is off cooldown
            abilities = await self.get_available_abilities(reaper)
            enemy_ground_units_in_grenade_range = enemy_ground_units_in_grenade_range.sorted(
                lambda x: x.distance_to(reaper), reverse=True
            )
            furthest_enemy: Unit = None
            for enemy in enemy_ground_units_in_grenade_range:
                if await self.can_cast(reaper, AbilityId.KD8CHARGE_KD8CHARGE, enemy, cached_abilities_of_unit=abilities):
                    furthest_enemy: Unit = enemy
                    break
            if furthest_enemy:
                reaper(AbilityId.KD8CHARGE_KD8CHARGE, furthest_enemy)
                return True
        return False

    async def unit_move_to_target_executed(self, unit: Unit, can_attack_enemies: Units) -> bool:
        """Move to nearest enemy unit/building because no enemy is within units range."""

        if can_attack_enemies:
            closest_enemy: Unit = can_attack_enemies.closest_to(unit)
            unit.move(closest_enemy)
            return True
        else:
            target = self.enemy_structures.random_or(self.enemy_start_locations[0]).position
            unit.attack(target)
            # unit.move(random.choice(self.enemy_start_locations))
        return True

    async def reaper_retrieve_to_regenerate_executed(self, reaper: Unit, enemies_can_attack_ground: Units) -> bool:
        """Keep the reaper in the range 15 of the closest enemy if less than 20hp to enable regenerating process."""
 
        enemy_threats_close: Units = enemies_can_attack_ground.filter(lambda unit: unit.distance_to(reaper) < 15)
        if reaper.health_percentage < 0.3 and enemy_threats_close:
            retreat_points: Set[Point2] = ( self.get_pathable_neighbors(reaper.position, distance=2) | 
                                          self.get_pathable_neighbors(reaper.position, distance=4))
            if retreat_points:
                closest_enemy: Unit = enemy_threats_close.closest_to(reaper)
                # Just the point furthest from the enemy
                retreat_point: Unit = closest_enemy.position.furthest(retreat_points)
                reaper.move(retreat_point)
                return True
        return False
            
    async def unit_stay_out_of_range_from_enemy_executed(self, unit: Unit, unit_range: float, enemies_can_attack_ground: Units) -> bool:
        """Retreat the unit if enemy unit is closer than unit range."""

        enemy_threats_very_close: Units = enemies_can_attack_ground.filter(lambda unit: unit.distance_to(unit) < (unit_range - 0.5))
        if unit.weapon_cooldown != 0 and enemy_threats_very_close:
            retreat_points: Set[Point2] = ( self.get_pathable_neighbors(unit.position, distance=2) | 
                                          self.get_pathable_neighbors(unit.position, distance=4))
            if retreat_points:
                closest_enemy: Unit = enemy_threats_very_close.closest_to(unit)
                # The point furthest from the enemy with respect to the current units position
                retreat_point: Point2 = max(retreat_points, key=lambda x: x.distance_to(closest_enemy) - x.distance_to(unit))
                unit.move(retreat_point)
                return True
        return False

    async def reaper_actions(self):
        """Excecute reaper's action according the situation."""

        reaper = UnitTypeId.REAPER
        enemies: Units = self.enemy_units | self.enemy_structures
        enemies_can_attack: Units = enemies.filter(lambda unit: unit.can_attack_ground and unit.ground_range > 2) # Trying to elimintate the workers
        for r in self.units(reaper):
            if await self.reaper_retrieve_to_regenerate_executed(r, enemies):
                continue
            if await self.unit_attack_executed(r, enemies.filter(lambda unit: unit.distance_to(r) < self.REAPER_RANGE and not unit.is_flying)):
                continue
            if self.units(reaper).idle.amount > self.aggresive_units[reaper]['defense']:
                if await self.unit_defend_executed(r, enemies.filter(lambda unit: not unit.is_flying)):
                    continue
            if await self.reaper_throw_grenade_executed(r, enemies_can_attack):
                continue
            if await self.unit_stay_out_of_range_from_enemy_executed(r, self.REAPER_RANGE, enemies_can_attack):
                continue
            if self.units(reaper).idle.amount > self.aggresive_units[reaper]['attack']:
                if await self.unit_move_to_target_executed(r, self.enemy_units.not_flying):
                    continue

    async def marine_actions(self):
        """Excecute marine's action according the situation."""

        marine = UnitTypeId.MARINE
        enemies: Units = self.enemy_units | self.enemy_structures
        enemies_can_attack: Units = enemies.filter(lambda unit: unit.can_attack_ground and unit.ground_range > 3) # Trying to elimintate the workers
        for m in self.units(marine).idle:
            if await self.unit_stay_out_of_range_from_enemy_executed(m, self.MARINE_RANGE, enemies_can_attack):
                continue
            if await self.unit_attack_executed(m, enemies.filter(lambda unit: unit.distance_to(m) < self.MARINE_RANGE)):
                continue
            if self.units(marine).idle.amount > self.aggresive_units[marine]['defense']:
                if await self.unit_defend_executed(m, enemies):
                    continue
            if self.units(marine).idle.amount > self.aggresive_units[marine]['attack']:
                if await self.unit_move_to_target_executed(m, enemies):
                    continue

    async def use_orbitalcommand_ability(self):
        """Manage orbital energy and drop mules."""

        for oc in self.townhalls(UnitTypeId.ORBITALCOMMAND).filter(lambda x: x.energy >= 50):
            mfs: Units = self.mineral_field.closer_than(10, oc)
            if mfs:
                mf: Unit = max(mfs, key=lambda x: x.mineral_contents)
                oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, mf)

    async def on_step(self, iteration: int):
            self.iteration = iteration
            # TODO: self.step_time() use step time to detect the iterations per minute (to dynamicaly detect)
            self.minute_of_the_game = iteration / self.ITERATIONS_PER_MINUTE
            if self.minute_of_the_game % 1 == 0:
                print(f'Minutes of the game approximation: {self.minute_of_the_game}')
            await self.build_workers(22)
            await self.build_supplydepots(6, 10)
            await self.morph_cc_to_orbitalcommand()
            # await self.build_lab_and_research_medivac()
            await self.expand_to_new_location(4)
            await self.build_barracks(5, 10)
            await self.build_refineries(2, 10)
            # await self.build_factory(1)
            await self.train_reapers()
            # await self.train_marines()
            if iteration % 25 == 0:
                await self.custom_distribute_workers()
            await self.reaper_actions()
            await self.group_units()
            # await self.marine_actions()
            await self.workers_back_to_work()
            await self.use_orbitalcommand_ability()

    # Helper functions
    async def custom_distribute_workers(self, performance_heavy=True, only_saturate_gas=False):
        """Distribute workers function rewritten, the default distribute_workers() function did not saturate gas quickly enough."""

        mineral_tags = [x.tag for x in self.mineral_field]
        gas_building_tags = [x.tag for x in self.gas_buildings]

        worker_pool = Units([], self)
        worker_pool_tags = set()

        # Find all gas_buildings that have surplus or deficit
        deficit_gas_buildings = {}
        surplusgas_buildings = {}
        for g in self.gas_buildings.filter(lambda x: x.vespene_contents > 0):
            # Only loop over gas_buildings that have still gas in them
            deficit = g.ideal_harvesters - g.assigned_harvesters
            if deficit > 0:
                deficit_gas_buildings[g.tag] = {"unit": g, "deficit": deficit}
            elif deficit < 0:
                surplus_workers = self.workers.closer_than(10, g).filter(
                    lambda w: w not in worker_pool_tags and len(w.orders) == 1 and w.orders[0].ability.id in
                    [AbilityId.HARVEST_GATHER] and w.orders[0].target in gas_building_tags
                )
                for _ in range(-deficit):
                    if surplus_workers.amount > 0:
                        w = surplus_workers.pop()
                        worker_pool.append(w)
                        worker_pool_tags.add(w.tag)
                surplusgas_buildings[g.tag] = {"unit": g, "deficit": deficit}

        # Find all townhalls that have surplus or deficit
        deficit_townhalls = {}
        surplus_townhalls = {}
        if not only_saturate_gas:
            for th in self.townhalls:
                deficit = th.ideal_harvesters - th.assigned_harvesters
                if deficit > 0:
                    deficit_townhalls[th.tag] = {"unit": th, "deficit": deficit}
                elif deficit < 0:
                    surplus_workers = self.workers.closer_than(10, th).filter(
                        lambda w: w.tag not in worker_pool_tags and len(w.orders) == 1 and w.orders[0].ability.id in
                        [AbilityId.HARVEST_GATHER] and w.orders[0].target in mineral_tags
                    )
                    # worker_pool.extend(surplus_workers)
                    for _ in range(-deficit):
                        if surplus_workers.amount > 0:
                            w = surplus_workers.pop()
                            worker_pool.append(w)
                            worker_pool_tags.add(w.tag)
                    surplus_townhalls[th.tag] = {"unit": th, "deficit": deficit}

            if all([len(deficit_gas_buildings) == 0, len(surplusgas_buildings) == 0, len(surplus_townhalls) == 0 or deficit_townhalls == 0]):
                # Cancel early if there is nothing to balance
                return

        # Check if deficit in gas less or equal than what we have in surplus, else grab some more workers from surplus bases
        deficit_gas_count = sum(
            gasInfo["deficit"] for gasTag, gasInfo in deficit_gas_buildings.items() if gasInfo["deficit"] > 0
        )
        surplus_count = sum(
            -gasInfo["deficit"] for gasTag, gasInfo in surplusgas_buildings.items() if gasInfo["deficit"] < 0
        )
        surplus_count += sum(
            -townhall_info["deficit"] for townhall_tag, townhall_info in surplus_townhalls.items()
            if townhall_info["deficit"] < 0
        )

        if deficit_gas_count - surplus_count > 0:
            # Grab workers near the gas who are mining minerals
            for _gas_tag, gas_info in deficit_gas_buildings.items():
                if worker_pool.amount >= deficit_gas_count:
                    break
                workers_near_gas = self.workers.closer_than(10, gas_info["unit"]).filter(
                    lambda w: w.tag not in worker_pool_tags and len(w.orders) == 1 and w.orders[0].ability.id in
                    [AbilityId.HARVEST_GATHER] and w.orders[0].target in mineral_tags
                )
                while workers_near_gas.amount > 0 and worker_pool.amount < deficit_gas_count:
                    w = workers_near_gas.pop()
                    worker_pool.append(w)
                    worker_pool_tags.add(w.tag)

        # Now we should have enough workers in the pool to saturate all gases, and if there are workers left over, make them mine at townhalls that have mineral workers deficit
        for _gas_tag, gas_info in deficit_gas_buildings.items():
            if performance_heavy:
                # Sort furthest away to closest (as the pop() function will take the last element)
                worker_pool.sort(key=lambda x: x.distance_to(gas_info["unit"]), reverse=True)
            for _ in range(gas_info["deficit"]):
                if worker_pool.amount > 0:
                    w = worker_pool.pop()
                    if len(w.orders) == 1 and w.orders[0].ability.id in [AbilityId.HARVEST_RETURN]:
                        w.gather(gas_info["unit"], queue=True)
                    else:
                        w.gather(gas_info["unit"])

        if not only_saturate_gas:
            # If we now have left over workers, make them mine at bases with deficit in mineral workers
            for townhall_tag, townhall_info in deficit_townhalls.items():
                if performance_heavy:
                    # Sort furthest away to closest (as the pop() function will take the last element)
                    worker_pool.sort(key=lambda x: x.distance_to(townhall_info["unit"]), reverse=True)
                for _ in range(townhall_info["deficit"]):
                    if worker_pool.amount > 0:
                        w = worker_pool.pop()
                        mf = self.mineral_field.closer_than(10, townhall_info["unit"]).closest_to(w)
                        if len(w.orders) == 1 and w.orders[0].ability.id in [AbilityId.HARVEST_RETURN]:
                            w.gather(mf, queue=True)
                        else:
                            w.gather(mf)

    async def filter_units_in_range_for_grouping(self, th_position: Point2, unit_type_id: int, grouping_range: int):
        """Filter units within the specified range from the townhall for grouping."""

        units_in_range = []
        for unit in self.units(unit_type_id).idle:
            distance_to_townhall = unit.position.distance_to(th_position)
            if distance_to_townhall <= grouping_range:
                units_in_range.append(unit)

        return units_in_range

    async def select_best_grouping_location(self, th_position: Point2, max_distance_from_th: int, enemy_position: Point2) -> Point2:
        """Find the best location to group units within given distance from the townhall, while also considering the enemy's position."""

        best_location: Point2 = None
        min_total_distance: float = float('inf')

        # Iterate over potential grouping locations within the specified range
        for x in range(int(th_position.x) - max_distance_from_th, int(th_position.x) + max_distance_from_th + 1):
            for y in range(int(th_position.y) - max_distance_from_th, int(th_position.y) + max_distance_from_th + 1):
                potential_location = Point2((x, y))

                # Calculate the total distance to the townhall and enemy
                distance_to_townhall = th_position.distance_to(potential_location)
                distance_to_enemy = enemy_position.distance_to(potential_location)

                # Calculate the weighted total distance, prioritizing closeness to the enemy
                total_distance = 0.7 * distance_to_enemy + 0.3 * distance_to_townhall

                # Update the best location if the current total distance is better
                if total_distance < min_total_distance:
                    best_location = potential_location
                    min_total_distance = total_distance

        return best_location

    async def count_builidngs_near_townhall(self, unit_type_id: int, max_distance: int, th_position: Point2) -> int:
        """Check number of given builidngs type near the townhall."""

        builidngs_count = 0
        for builidngs in self.structures(unit_type_id):
            if builidngs.position.distance_to(th_position) <= max_distance:
                builidngs_count += 1
        return builidngs_count

    def get_pathable_neighbors(self, position: Point2, distance: int = 1) -> Set[Point2]:
        """Create a set of coordinates to every direction from given position in the given distance."""

        neighbors = set()
        neighbors.add(Point2((position.x - distance, position.y)))  # North neighbor
        neighbors.add(Point2((position.x + distance, position.y)))  # South neighbor
        neighbors.add(Point2((position.x, position.y - distance)))  # West neighbor
        neighbors.add(Point2((position.x, position.y + distance)))  # East neighbor
        neighbors.add(Point2((position.x - distance, position.y - distance)))  # Northwest neighbor
        neighbors.add(Point2((position.x - distance, position.y + distance)))  # Northeast neighbor
        neighbors.add(Point2((position.x + distance, position.y - distance)))  # Southwest neighbor
        neighbors.add(Point2((position.x + distance, position.y + distance)))  # Southeast neighbor

        return set({x for x in neighbors if self.in_pathing_grid(x)})

def main():
    run_game(
        maps.get("sc2-ai-cup-2022"), 
        [Bot(Race.Terran, MarineReaperRushBot()), Computer(Race.Terran, Difficulty.Hard)],
        realtime=False
    )

if __name__ == "__main__":
    main()
