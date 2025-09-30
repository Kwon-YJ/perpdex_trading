"""exchange_guide.txt 자본 업데이트 유틸리티"""
import csv
from typing import Dict, List, Optional, Callable
import os


class ExchangeGuideUpdater:
    """exchange_guide.txt 파일의 현재자본 컬럼 업데이트"""

    def __init__(self, file_path: str, logger: Optional[Callable[[str], None]] = None):
        self.file_path = file_path
        self.logger = logger

    def _log(self, message: str):
        if self.logger:
            self.logger(message)

    def read_exchange_guide(self) -> List[Dict[str, str]]:
        """exchange_guide.txt 읽기"""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"{self.file_path} 파일을 찾을 수 없습니다")

        rows = []
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        return rows

    def write_exchange_guide(self, rows: List[Dict[str, str]]):
        """exchange_guide.txt 쓰기"""
        if not rows:
            return

        fieldnames = rows[0].keys()

        with open(self.file_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def update_capital(self, exchange_name: str, current_capital: float) -> bool:
        """
        특정 거래소의 현재자본 업데이트

        Args:
            exchange_name: 거래소명
            current_capital: 현재 자본

        Returns:
            성공 여부
        """
        try:
            rows = self.read_exchange_guide()

            updated = False
            for row in rows:
                if row.get('거래소명') == exchange_name:
                    row['현재자본'] = str(current_capital)
                    updated = True
                    break

            if updated:
                self.write_exchange_guide(rows)
                self._log(f"✓ {exchange_name} 현재자본 업데이트: {current_capital}")
                return True
            else:
                self._log(f"⚠️ {exchange_name}: exchange_guide.txt에서 거래소를 찾지 못함")
                return False

        except Exception as e:
            self._log(f"✗ exchange_guide.txt 업데이트 실패: {e}")
            return False

    def update_multiple_capitals(self, capital_map: Dict[str, float]) -> Dict[str, bool]:
        """
        여러 거래소의 현재자본 일괄 업데이트

        Args:
            capital_map: {거래소명: 현재자본} 딕셔너리

        Returns:
            {거래소명: 성공여부} 딕셔너리
        """
        try:
            rows = self.read_exchange_guide()

            results = {}
            for row in rows:
                exchange_name = row.get('거래소명')
                if exchange_name in capital_map:
                    row['현재자본'] = str(capital_map[exchange_name])
                    results[exchange_name] = True
                    self._log(f"✓ {exchange_name} 현재자본 업데이트: {capital_map[exchange_name]}")

            # 업데이트되지 않은 거래소 표시
            for exchange_name in capital_map:
                if exchange_name not in results:
                    results[exchange_name] = False
                    self._log(f"⚠️ {exchange_name}: exchange_guide.txt에서 거래소를 찾지 못함")

            self.write_exchange_guide(rows)
            return results

        except Exception as e:
            self._log(f"✗ exchange_guide.txt 업데이트 실패: {e}")
            return {exchange_name: False for exchange_name in capital_map}

    def get_exchange_info(self, exchange_name: str) -> Dict[str, str]:
        """특정 거래소 정보 조회"""
        try:
            rows = self.read_exchange_guide()
            for row in rows:
                if row.get('거래소명') == exchange_name:
                    return row
            return {}
        except Exception as e:
            self._log(f"✗ 거래소 정보 조회 실패: {e}")
            return {}

    def get_all_exchanges(self) -> List[str]:
        """모든 거래소명 조회"""
        try:
            rows = self.read_exchange_guide()
            return [row.get('거래소명') for row in rows if row.get('거래소명')]
        except Exception as e:
            self._log(f"✗ 거래소 목록 조회 실패: {e}")
            return []
