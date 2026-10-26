"""O mundo: América do Sul em grade lat/lon, depósitos e cidades REAIS.

Posições são aproximações geográficas reais (lat/lon). Depósitos têm
tamanho/teor OCULTOS (fog-of-war) até uma empresa sondar a célula.
Unidades: minérios/metais em toneladas, dinheiro em US$.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Grade: lat de -56 a 14, lon de -82 a -32, células de 2.5 graus.
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, CELL = -56.0, 14.0, -82.0, -32.0, 2.5
ROWS = int((LAT_MAX - LAT_MIN) / CELL)  # 28
COLS = int((LON_MAX - LON_MIN) / CELL)  # 20


def cell_of(lat: float, lon: float) -> tuple[int, int]:
    r = min(ROWS - 1, max(0, int((lat - LAT_MIN) / CELL)))
    c = min(COLS - 1, max(0, int((lon - LON_MIN) / CELL)))
    return (r, c)


def cell_center(cell: tuple[int, int]) -> tuple[float, float]:
    r, c = cell
    return (LAT_MIN + (r + 0.5) * CELL, LON_MIN + (c + 0.5) * CELL)


@dataclass
class Deposit:
    """Depósito mineral real. size/grade são a verdade oculta do mundo."""
    name: str
    resource: str          # commodity bruta: lithium_ore, copper_ore, iron_ore, oil
    lat: float
    lon: float
    size_t: float          # toneladas extraíveis (oculto)
    grade: float           # teor 0..1: fração aproveitável (oculto)
    cell: tuple[int, int] = field(init=False)

    def __post_init__(self):
        self.cell = cell_of(self.lat, self.lon)


# Depósitos reais (posição aproximada; tamanho/teor são parâmetros do mundo,
# calibrados por ordem de grandeza das reservas conhecidas).
DEPOSITS: list[Deposit] = [
    Deposit("Salar de Atacama", "lithium_ore", -23.5, -68.2, 900_000, 0.85),
    Deposit("Salar de Uyuni", "lithium_ore", -20.1, -67.5, 1_400_000, 0.62),
    Deposit("Salinas de Jujuy", "lithium_ore", -24.2, -66.2, 500_000, 0.55),
    Deposit("Escondida (Norte do Chile)", "copper_ore", -24.3, -69.1, 2_600_000, 0.80),
    Deposit("Chuquicamata", "copper_ore", -22.3, -68.9, 1_800_000, 0.66),
    Deposit("Sul do Peru (Toquepala)", "copper_ore", -17.3, -70.2, 1_500_000, 0.60),
    Deposit("Carajás", "iron_ore", -6.0, -50.3, 3_200_000, 0.88),
    Deposit("Quadrilátero Ferrífero", "iron_ore", -20.0, -43.8, 2_400_000, 0.72),
    Deposit("Pré-sal (Bacia de Santos)", "oil", -24.8, -43.5, 2_000_000, 0.78),
    Deposit("Vaca Muerta", "oil", -38.9, -68.6, 1_600_000, 0.70),
]


@dataclass
class City:
    name: str
    lat: float
    lon: float
    demand_weight: float   # peso relativo na demanda das cidades
    cell: tuple[int, int] = field(init=False)

    def __post_init__(self):
        self.cell = cell_of(self.lat, self.lon)


CITIES: list[City] = [
    City("São Paulo", -23.5, -46.6, 1.00),
    City("Rio de Janeiro", -22.9, -43.2, 0.55),
    City("Buenos Aires", -34.6, -58.4, 0.62),
    City("Santiago", -33.4, -70.7, 0.45),
    City("Lima", -12.0, -77.0, 0.40),
    City("Bogotá", 4.7, -74.1, 0.42),
    City("Belo Horizonte", -19.9, -43.9, 0.30),
    City("Porto Alegre", -30.0, -51.2, 0.26),
]
