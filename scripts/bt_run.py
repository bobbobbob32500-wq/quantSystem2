import sys, os, json, pickle
sys.path.insert(0, ".")
import numpy as np, pandas as pd
from datetime import time as dt_time
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams

print("Loading data...", flush=True)
with open("output/bt_data.pkl", "rb") as f2:
    D = pickle.load(f2)
idata = D["idata"]; ins = D["ins"]; outs = D["outs"]; ma120 = D["ma120"]
feat = D["feat"]; pm = D["pm"]; params = D["params"]
config = ConfigManager(); db = DatabaseManager(config)
st = BreakoutStrategy(db=db, params=params)
print(f"Intraday: {len(idata)} stocks, In: {len(ins)}d, Out: {len(outs)}d", flush=True)
