# -*- coding: utf-8 -*-
import pandas as pd

df = pd.read_csv("BTCTUSD-12h-2025-05.csv", header=None)
print(df[0].head(10))
