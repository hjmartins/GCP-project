"""Derivação de seeds.

Toda aleatoriedade do gerador passa por aqui. Usamos ``SeedSequence`` em vez de ``hash()``
porque o ``hash()`` de strings do Python muda a cada processo (PYTHONHASHSEED).
"""

from datetime import date

import numpy as np

# Domínios separados: o cadastro depende só da seed base (os mesmos usuários todo dia);
# os dados diários dependem da seed base e da data.
_CATALOG = 0
_DAILY = 1


def catalog_rng(seed_base: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed_base, _CATALOG]))


def daily_rng(seed_base: int, day: date) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed_base, _DAILY, day.toordinal()]))
