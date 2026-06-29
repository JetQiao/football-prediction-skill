"""自包含 HTML 报告。"""

from .renderer import render_report, write_report
from .tournament import write_tournament_report

__all__ = ["render_report", "write_report", "write_tournament_report"]
