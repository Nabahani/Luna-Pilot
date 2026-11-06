import spiceypy as sp
import numpy as np
from naif_de440 import de440
from naif_leapseconds import leapseconds

kernels = [
    leapseconds,
    de440,
    "kernels/moon_orientation/pck00011.tpc",
    "kernels/moon_orientation/moon_de440_220930.tf",
    "kernels/moon_orientation/moon_pa_de440_200625.bpc",
]

for kernel in kernels:
    sp.furnsh(str(kernel))

et = sp.str2et("2027-01-01T00:00:00")

for body in ["SUN", "EARTH"]:
    position, light_time = sp.spkpos(
        body, et, "MOON_PA_DE440", "NONE", "MOON"
    )

    distance = np.linalg.norm(position)

    print(f"\n{body}")
    print("Position (km):", position)
    print("Distance (km):", round(distance, 2))

sp.kclear()