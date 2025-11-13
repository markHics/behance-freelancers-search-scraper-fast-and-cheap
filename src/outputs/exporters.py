thonimport json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping

import pandas as pd

logger = logging.getLogger(__name__)

class ExportFormatError(ValueError):
    """Raised when an unsupported export format is requested."""

@dataclass
class ExportManager:
    """
    Handles export of scraped records to multiple tabular formats.
    """

    output_dir: str

    def __post_init__(self) -> None:
        self.output_dir = self.output_dir or "."
        if not os.path.exists(self.output_dir):
            logger.info("Creating output directory: %s", self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)

    def export(self, records: List[Mapping[str, Any]], formats: Iterable[str], base_filename: str) -> None:
        """
        Export the given records to the supplied formats.

        Supported formats:
            - json
            - csv
            - excel
            - html
        """
        # Convert to list to consume iterable and avoid re-use issues
        records = list(records)
        formats = [f.strip().lower() for f in formats]

        logger.debug(
            "Exporting %d records to formats %s with base filename '%s'",
            len(records),
            formats,
            base_filename,
        )

        for fmt in formats:
            if fmt == "json":
                self._export_json(records, base_filename)
            elif fmt == "csv":
                self._export_csv(records, base_filename)
            elif fmt in ("xlsx", "excel"):
                self._export_excel(records, base_filename)
            elif fmt == "html":
                self._export_html(records, base_filename)
            else:
                raise ExportFormatError(f"Unsupported export format: {fmt}")

    # ------------------------------------------------------------------ #
    # Individual format exporters
    # ------------------------------------------------------------------ #

    def _export_json(self, records: List[Mapping[str, Any]], base_filename: str) -> None:
        path = os.path.join(self.output_dir, f"{base_filename}.json")
        logger.info("Writing JSON output to %s", path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.error("Failed to write JSON output: %s", exc)
            raise

    def _to_dataframe(self, records: List[Mapping[str, Any]]) -> pd.DataFrame:
        if not records:
            logger.warning("No records to export; creating empty DataFrame.")
            return pd.DataFrame()
        return pd.DataFrame.from_records(records)

    def _export_csv(self, records: List[Mapping[str, Any]], base_filename: str) -> None:
        df = self._to_dataframe(records)
        path = os.path.join(self.output_dir, f"{base_filename}.csv")
        logger.info("Writing CSV output to %s", path)
        try:
            df.to_csv(path, index=False)
        except OSError as exc:
            logger.error("Failed to write CSV output: %s", exc)
            raise

    def _export_excel(self, records: List[Mapping[str, Any]], base_filename: str) -> None:
        df = self._to_dataframe(records)
        path = os.path.join(self.output_dir, f"{base_filename}.xlsx")
        logger.info("Writing Excel output to %s", path)
        try:
            df.to_excel(path, index=False, engine="openpyxl")
        except OSError as exc:
            logger.error("Failed to write Excel output: %s", exc)
            raise

    def _export_html(self, records: List[Mapping[str, Any]], base_filename: str) -> None:
        df = self._to_dataframe(records)
        path = os.path.join(self.output_dir, f"{base_filename}.html")
        logger.info("Writing HTML output to %s", path)
        try:
            html_table = df.to_html(index=False)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_table)
        except OSError as exc:
            logger.error("Failed to write HTML output: %s", exc)
            raise