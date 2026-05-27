from abc import ABC, abstractmethod

import pandas as pd
import geopandas as gpd

from src.domain.enums import EPSGCode


class IBytesService(ABC):
    @staticmethod
    @abstractmethod
    def convert_parquet_bytes_to_df(data: bytes) -> pd.DataFrame:
        """
        Converts a byte array to a pandas DataFrame. This assumes that the files a parquet file
        :param data: Byte array of the parquet file. Often downloaded from blob storage.
        :return: Dataframe representation of the byte array.
        :rtype: pd.DataFrame
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def convert_parquet_bytes_to_gdf(data: bytes, epsg_code: EPSGCode) -> gpd.GeoDataFrame:
        """
        Converts a byte array to a GeoPandas GeoDataFrame. This assumes that the file is a parquet file and that
        there is a geometry column with geometries represented as WKB.

        :param data: Byte array of the parquet file. Often downloaded from blob storage.
        :param epsg_code: EPSG code for the coordinate reference system (CRS).
        :return: GeoDataFrame representation of the byte array.
        :rtype: gpd.GeoDataFrame
        :raises NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def convert_fgb_bytes_to_gdf(
            layers: list[bytes],
            crs_in: EPSGCode = EPSGCode.WGS84,
            crs_out: EPSGCode = EPSGCode.WGS84
    ) -> gpd.GeoDataFrame:
        """
        Converts a byte array to a GeoPandas GeoDataFrame. This assumes that the files are in FlatGeobuf format.
        :param layers: Layers in the FGB file as byte arrays.
        :param crs_out: Coordinate reference system to convert the GeoDataFrame to. Default is WGS84.
        :param crs_in: Coordinate reference system of the input GeoDataFrame.
        :return: GeoDataFrame representation of the byte array.
        :rtype: gpd.GeoDataFrame
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def convert_df_to_parquet_bytes(df: pd.DataFrame | gpd.GeoDataFrame) -> bytes:
        """
        Converts a Pandas DataFrame or GeoPandas GeoDataFrame to a byte array in parquet format.
        :param df: Pandas DataFrame or GeoPandas GeoDataFrame to convert.
        :return: Byte array representation of the DataFrame in parquet format.
        :rtype: bytes
        """
        raise NotImplementedError

