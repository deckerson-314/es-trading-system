from pathlib import Path
L=[]
L.append('#!/usr/bin/env python3')
L.append('from __future__ import annotations')
L.append('import csv,re,statistics,sys')
L.append('from collections import Counter')
L.append('from dataclasses import dataclass')
L.append('from pathlib import Path')
L.append("NEW=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-16-1.csv')")
L.append("OLD=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-11-1.csv')")
L.append("RN_span='Avg Trade Span (min, bar grid) (OOS aggregate)'")
L.append("RN_oosp='Total Profit ($) (OOS aggregate)'")
