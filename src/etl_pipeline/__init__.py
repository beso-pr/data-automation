"""Multi-API ETL pipeline.

Extracts multi-currency sales from CSV, enriches with FX rates and weather data
from public APIs, lands tidy tables in SQLite, and renders an HTML report.
"""

__version__ = "0.1.0"
