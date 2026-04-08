# -*- coding: utf-8 -*-
# test_sensory_matrix.py
from sensory_matrix import SensoryMatrix

def test_fetch():
    sm = SensoryMatrix("BTCUSDT", "1h", "2 days")
    df = sm.get_data()
    print(df.head())
    print(f"Data shape: {df.shape}")

if __name__ == "__main__":
    test_fetch()
