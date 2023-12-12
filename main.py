from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty

from AI.seminars.cv7.pantano.reaperMarineRushBot import MarineReaperRushBot
from AI.seminars.cv7.pantano.marineRushExampleBot import MarineRushBot

run_game(
    maps.get("sc2-ai-cup-2022"),
    [
        Bot(Race.Terran, MarineReaperRushBot()),
        Bot(Race.Terran, MarineRushBot())
    # Computer(Race.Terran, Difficulty.Medium)
    ],
    realtime=True
)
