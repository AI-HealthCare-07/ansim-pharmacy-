#!/usr/bin/env python3
"""
DB(medicines 테이블)에 저장된 낱알 이미지 URL을 조회하여
data/pill_images/{ITEM_SEQ}.jpg 로 일괄 다운로드하는 스크립트.

주요 기능:
  - 이미 존재하는 파일은 건너뛰기 (Resume 지원)
  - ThreadPoolExecutor를 통한 고속 병렬 다운로드
  - 공공기관(GPKI/KISA) SSL 인증서 호환 (SSL Unverified Context)
  - 임시 파일 쓰기 후 원자적 Rename으로 불완전 다운로드 방지
  - 실시간 tqdm 진행률 표시
  - 다운로드 실패 목록 로그(failed_downloads.log) 기록
  - 최종 통계 및 저장 파일 개수 집계
"""

import argparse
import asyncio
import os
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import asyncpg
from dotenv import dotenv_values
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
env_vars = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key) or env_vars.get(key) or default


# SSL 설정 (식약처 nedrug.mfds.go.kr의 공공 GPKI 인증서 에러 방지)
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


async def fetch_target_images(limit: int | None = None) -> list[tuple[str, str]]:
    """DB에서 낱알 이미지 URL이 있는 품목 목록 조회"""
    pg_host = get_env("POSTGRES_HOST", "localhost")
    pg_port = int(get_env("POSTGRES_PORT", "5432"))
    pg_user = get_env("POSTGRES_USER", "postgres")
    pg_password = get_env("POSTGRES_PASSWORD", "postgres1234")
    pg_db = get_env("POSTGRES_DB", "ai_health")

    conn = await asyncpg.connect(
        host=pg_host,
        port=pg_port,
        user=pg_user,
        password=pg_password,
        database=pg_db,
    )

    query = """
        SELECT item_seq, item_image
        FROM medicines
        WHERE item_image IS NOT NULL AND trim(item_image) != ''
        ORDER BY item_seq ASC
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = await conn.fetch(query)
    await conn.close()
    return [(r["item_seq"], r["item_image"].strip()) for r in rows]


def download_single_image(
    item_seq: str,
    url: str,
    output_dir: Path,
    retries: int = 3,
    timeout: int = 15,
) -> tuple[str, bool, str | None]:
    """단일 이미지 다운로드 (임시 파일 저장 후 rename)"""
    dest_path = output_dir / f"{item_seq}.jpg"
    tmp_path = output_dir / f"{item_seq}.jpg.tmp"

    # 이미 존재하는 파일 검사 (Resume)
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return item_seq, True, "SKIPPED"

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = resp.read()
                if not data:
                    raise RuntimeError("Empty response")

                with open(tmp_path, "wb") as f:
                    f.write(data)

                # 원자적 이동
                tmp_path.replace(dest_path)
                return item_seq, True, None
        except Exception as e:
            last_error = str(e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            time.sleep(0.5 * attempt)

    return item_seq, False, last_error


def main():
    parser = argparse.ArgumentParser(description="의약품 낱알 이미지 병렬 다운로드 스크립트")
    parser.add_argument("--workers", type=int, default=30, help="동시 다운로드 스레드 수 (기본: 30)")
    parser.add_argument("--output-dir", type=str, default="data/pill_images", help="저장 디렉터리 경로")
    parser.add_argument("--limit", type=int, default=None, help="다운로드할 최대 개수 제한 (테스트용)")
    parser.add_argument("--retries", type=int, default=3, help="실패 시 재시도 횟수 (기본: 3)")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP 타임아웃(초) (기본: 15)")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    failed_log_path = output_dir / "failed_downloads.log"

    print("==================================================")
    print("=== [의약품 낱알 이미지 일괄 병렬 다운로드] ===")
    print(f"저장 위치: {output_dir}")
    print(f"작업 스레드 수: {args.workers}")
    if args.limit:
        print(f"건수 제한: 최대 {args.limit:,}건")
    print("==================================================")

    # 1. DB에서 대상 조회
    print("\n[1/3] DB에서 대상 낱알 이미지 URL 조회 중...")
    targets = asyncio.run(fetch_target_images(args.limit))
    total_targets = len(targets)
    print(f"  -> 다운로드 대상 품목 수: {total_targets:,}건")

    if not targets:
        print("다운로드할 대상이 없습니다.")
        return

    # 2. Resume 사전 검사
    print("\n[2/3] 기존 저장된 파일 검사 (Resume 체크 중)...")
    pending = []
    already_downloaded = 0
    for seq, url in targets:
        p = output_dir / f"{seq}.jpg"
        if p.exists() and p.stat().st_size > 0:
            already_downloaded += 1
        else:
            pending.append((seq, url))

    print(f"  -> 이미 다운로드 완료된 파일: {already_downloaded:,}건 (건너뜀)")
    print(f"  -> 새로 다운로드할 파일: {len(pending):,}건")

    if not pending:
        print("\n모든 이미지가 이미 다운로드되어 있습니다.")
        existing_files = [f for f in output_dir.glob("*.jpg") if f.is_file() and f.stat().st_size > 0]
        print(f"최종 저장된 이미지 파일 개수: {len(existing_files):,}개")
        return

    # 3. ThreadPoolExecutor 병렬 다운로드
    print(f"\n[3/3] 병렬 다운로드 시작 (스레드 {args.workers}개)...")
    success_count = 0
    fail_count = 0
    failed_items = []

    start_time = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                download_single_image,
                seq,
                url,
                output_dir,
                args.retries,
                args.timeout,
            ): (seq, url)
            for seq, url in pending
        }

        with tqdm(total=len(pending), desc="다운로드 진행률", unit="img") as pbar:
            for future in as_completed(futures):
                seq, url = futures[future]
                try:
                    item_seq, success, reason = future.result()
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                        failed_items.append((seq, url, reason))
                except Exception as exc:
                    fail_count += 1
                    failed_items.append((seq, url, str(exc)))
                pbar.update(1)

    elapsed = time.time() - start_time

    # 실패 로그 작성
    if failed_items:
        with open(failed_log_path, "w", encoding="utf-8") as f:
            for seq, url, reason in failed_items:
                f.write(f"ITEM_SEQ: {seq}\tURL: {url}\tREASON: {reason}\n")

    # 최종 저장 파일 집계
    existing_files = [f for f in output_dir.glob("*.jpg") if f.is_file() and f.stat().st_size > 0]

    print("\n==================================================")
    print("=== 다운로드 완료 요약 ===")
    print(f"소요 시간: {elapsed:.1f}초 ({len(pending) / max(elapsed, 0.001):.1f} imgs/s)")
    print(f"  - 전체 대상 품목: {total_targets:,}건")
    print(f"  - 사전 기완료(건너뜀): {already_downloaded:,}건")
    print(f"  - 이번 실행 성공: {success_count:,}건")
    print(f"  - 이번 실행 실패: {fail_count:,}건")
    if fail_count > 0:
        print(f"    (실패 상세 로그: {failed_log_path})")
    print(f"★ 최종 저장된 총 이미지 파일 개수: {len(existing_files):,}개")
    print("==================================================")


if __name__ == "__main__":
    main()
