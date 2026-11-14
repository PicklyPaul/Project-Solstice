import requests
import pandas as pd
import numpy as np
import io
from astroquery.jplhorizons import Horizons as jpl
import astropy.units as u

# Reuse HTTP session for faster NASA API calls
SESSION = requests.Session()


def lunar_elev(lat, lon):
    """Fetches LOLA elevation (in meters) near (lat, lon) from NASA PDS ODE."""
    # Convert longitude to 0-360° range required by NASA ODE LOLA
    lon_360 = lon % 360.0

    lat_min = max(-90.0, lat - 0.02)
    lat_max = min(90.0, lat + 0.02)

    # Expand longitude window near poles so the bounding box has physical width
    cos_lat = max(0.05, np.cos(np.deg2rad(lat)))
    dlon = min(2.0, 0.02 / cos_lat)
    lon_min = max(0.0, lon_360 - dlon)
    lon_max = min(360.0, lon_360 + dlon)

    api_url = (
        f"https://oderest.rsl.wustl.edu/livegds?query=lolardr&o=j&results=u"
        f"&minlat={lat_min}&maxlat={lat_max}&westlon={lon_min}&eastlon={lon_max}"
    )

    try:
        response = SESSION.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()

        gds = data.get("GDSResults", {})
        if "ResultFiles" not in gds or not gds["ResultFiles"].get("ResultFile"):
            print("ODE LOLA returned no files for this box; defaulting elevation to 0m.")
            return 0.0

        # Pick the first CSV result file
        result_files = gds["ResultFiles"]["ResultFile"]
        if isinstance(result_files, dict):
            result_files = [result_files]

        csv_url = next((f["URL"] for f in result_files if f["URL"].endswith(".csv")), result_files[0]["URL"])
        file_res = SESSION.get(csv_url, timeout=15)

        df_lh = pd.read_csv(io.StringIO(file_res.content.decode("utf-8")))
        df_lh.columns = df_lh.columns.str.strip()

        df_lh["Pt_Longitude"] = pd.to_numeric(df_lh["Pt_Longitude"], errors="coerce")
        df_lh["Pt_Latitude"] = pd.to_numeric(df_lh["Pt_Latitude"], errors="coerce")
        df_lh = df_lh.dropna(subset=["Pt_Longitude", "Pt_Latitude"])

        # Fixed distance formula: compare Longitude to lon_360 and Latitude to lat
        dist_sq = (df_lh["Pt_Longitude"] - lon_360) ** 2 + (df_lh["Pt_Latitude"] - lat) ** 2
        closest_row = df_lh.loc[dist_sq.idxmin()]

        # Column index 2 is Topography/Elevation in meters
        elevation = float(closest_row.iloc[2])
        return elevation

    except Exception as e:
        print(f"lunar_elev fallback (0m) due to error: {e}")
        return 0.0


def Horizon(x, y, h, start, end, planet=10):
    """
    Queries JPL Horizons for both the Sun (10) and Earth (399) from lunar site (x=lon, y=lat, h=elev_m)
    and saves combined ephemeris to 'epher.csv'.
    """
    lsite = {
        "lon": x * u.deg,
        "lat": y * u.deg,
        "elevation": (h / 1000.0) * u.km,
        "body": 301  # Moon
    }

    dom = {
        "start": start,
        "stop": end,
        "step": "6h"  # 6-hour steps give smooth curves without slowing down JPL
    }

    # 1. Fetch Sun (ID = 10)
    sun_obj = jpl(id=10, location=lsite, epochs=dom)
    sun_df = sun_obj.ephemerides()["datetime_str", "EL", "AZ"].to_pandas()

    # 2. Fetch Earth (ID = 399)
    earth_obj = jpl(id=399, location=lsite, epochs=dom)
    earth_df = earth_obj.ephemerides()["EL", "AZ"].to_pandas()

    # Combine into a single DataFrame
    sun_df["Earth_EL"] = earth_df["EL"]
    sun_df["Earth_AZ"] = earth_df["AZ"]

    sun_df.to_csv("epher.csv")