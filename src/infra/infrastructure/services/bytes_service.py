from io import BytesIO

import geopandas as gpd
import pandas as pd
from shapely import from_wkb

from src.application.common import logger
from src.application.contracts import IBytesService
from src.domain.enums import EPSGCode


class BytesService(IBytesService):
    @staticmethod
    def convert_parquet_bytes_to_df(data: bytes) -> pd.DataFrame:
        return pd.read_parquet(BytesIO(data))

    @staticmethod
    def convert_parquet_bytes_to_gdf(data: bytes, epsg_code: EPSGCode) -> gpd.GeoDataFrame:
        df = BytesService.convert_parquet_bytes_to_df(data)
        df["geometry"] = df["geometry"].apply(from_wkb)

        gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=f"EPSG:{epsg_code.value}")
        return gdf

    @staticmethod
    def convert_fgb_bytes_to_gdf(
            layers: list[bytes],
            crs_in: EPSGCode = EPSGCode.WGS84,
            crs_out: EPSGCode = EPSGCode.WGS84
    ) -> gpd.GeoDataFrame:
        gdfs: list[gpd.GeoDataFrame] = []
        for layer in layers:
            gdf = gpd.read_file(layer, engine="pyogrio")
            gdfs.append(gdf)

        combined_gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=crs_in.value)
        if crs_in != crs_out:
            combined_gdf = combined_gdf.to_crs(crs_out.value)

        return combined_gdf

    @staticmethod
    def convert_df_to_parquet_bytes(df: pd.DataFrame | gpd.GeoDataFrame) -> bytes:
        if df.empty:
            logger.warning("Converting empty DataFrame to bytes.")

        buffer = BytesIO()
        df.to_parquet(buffer, index=False)
        buffer.seek(0)
        return buffer.read()

