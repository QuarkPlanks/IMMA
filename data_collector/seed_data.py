"""
data_collector/seed_data.py
────────────────────────────
常见注塑塑料牌号的种子列表，用于初始化数据库。
运行: python scraper.py --seed
"""

# 每一项为传给 fetch_grade() 的搜索字符串
SEED_GRADES: list[str] = [
    # ── ABS ──────────────────────────────────────────────────────────────────
    "ABS CHIMEI PA-757",
    "ABS CHIMEI PA-747",
    "ABS LG Chem HI-121H",
    "ABS Toray Toyolac 100",
    "ABS SABIC MG94",
    "ABS Styrolution Terluran GP-35",

    # ── PC ───────────────────────────────────────────────────────────────────
    "PC Covestro Makrolon 2205",
    "PC Covestro Makrolon 2405",
    "PC SABIC Lexan 141R",
    "PC SABIC Lexan HF1110R",

    # ── PC/ABS ───────────────────────────────────────────────────────────────
    "PC/ABS Covestro Bayblend T65",
    "PC/ABS SABIC Cycoloy C1000",

    # ── PP ───────────────────────────────────────────────────────────────────
    "PP LyondellBasell Moplen HP500N",
    "PP Borealis BA212E",
    "PP SABIC PP 579S",
    "PP Braskem F020HC",

    # ── PA6 ──────────────────────────────────────────────────────────────────
    "PA6 BASF Ultramid B3S",
    "PA6 Lanxess Durethan B30S",
    "PA6 DSM Akulon K222-D",

    # ── PA66 ─────────────────────────────────────────────────────────────────
    "PA66 DuPont Zytel 101L",
    "PA66 BASF Ultramid A3K",
    "PA66 Ascend Vydyne 21SPC",

    # ── POM ──────────────────────────────────────────────────────────────────
    "POM DuPont Delrin 100",
    "POM Celanese Hostaform C9021",
    "POM BASF Ultraform N2320",

    # ── PBT ──────────────────────────────────────────────────────────────────
    "PBT BASF Ultradur B4500",
    "PBT Celanese Celanex 2002",
    "PBT SABIC Valox 315",

    # ── PET ──────────────────────────────────────────────────────────────────
    "PET DuPont Rynite 530",
    "PET Invista Laser+ C92",

    # ── PMMA ─────────────────────────────────────────────────────────────────
    "PMMA Evonik Plexiglas 7N",
    "PMMA Arkema Altuglas V825T",

    # ── PS / HIPS ─────────────────────────────────────────────────────────────
    "HIPS CHIMEI PH-888G",
    "GPPS INEOS Styrocell M",

    # ── TPU ──────────────────────────────────────────────────────────────────
    "TPU BASF Elastollan 1185A",
    "TPU Covestro Desmopan 385E",

    # ── PEEK ─────────────────────────────────────────────────────────────────
    "PEEK Victrex 450G",

    # ── PPS ──────────────────────────────────────────────────────────────────
    "PPS Solvay Ryton R-4",
]
