import asyncio
import sys
import os
from datetime import datetime
import json
import logging
import time
from typing import List, Dict
from database import Database
from scraper import Pro4KingsScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("initial_scan.log"), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

SCAN_STATE_FILE = "scan_state.json"
DB_PATH = os.getenv("DATABASE_PATH", "pro4kings.db")
START_ID = 1
END_ID = 230000

CONCURRENT_WORKERS = 5
BATCH_SIZE = 50


class FastScanner:
    def __init__(self, db_path: str = DB_PATH, workers: int = CONCURRENT_WORKERS):
        self.db = Database(db_path)
        self.workers = workers
        self.scan_state = self.load_scan_state()
        self.stats = {
            "total_scanned": 0,
            "found": 0,
            "not_found": 0,
            "errors": 0,
            "retries_503": 0,
            "start_time": None,
            "end_time": None,
        }
        self.stats_lock = asyncio.Lock()
        self.last_progress_time = None
        self.last_progress_count = 0

    def load_scan_state(self) -> Dict:
        if os.path.exists(SCAN_STATE_FILE):
            try:
                with open(SCAN_STATE_FILE, "r") as f:
                    state = json.load(f)
                logger.info(f"Resuming from ID {state.get('last_id', START_ID)}")
                return state
            except Exception as e:
                logger.error(f"Error loading scan state: {e}")
        return {"last_id": START_ID - 1, "completed": False, "found_count": 0}

    def save_scan_state(self, last_id: int):
        self.scan_state["last_id"] = last_id
        self.scan_state["completed"] = last_id >= END_ID
        self.scan_state["found_count"] = self.stats["found"]
        try:
            with open(SCAN_STATE_FILE, "w") as f:
                json.dump(self.scan_state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving scan state: {e}")

    async def worker(
        self,
        worker_id: int,
        scraper: Pro4KingsScraper,
        player_ids_batches: List[List[str]],
    ):
        for batch_index, batch_ids in enumerate(player_ids_batches):
            try:
                logger.info(
                    f"Worker {worker_id}: Processing batch {batch_index + 1}/{len(player_ids_batches)} ({len(batch_ids)} IDs)"
                )
                profiles = await scraper.batch_get_profiles(batch_ids)

                for profile in profiles:
                    if profile:
                        profile_dict = {
                            "player_id": profile.player_id,
                            "player_name": profile.username,
                            "is_online": profile.is_online,
                            "last_connection": profile.last_seen,
                            "faction": profile.faction,
                            "faction_rank": profile.faction_rank,
                            "job": profile.job,
                            "warns": profile.warnings,
                            "played_hours": profile.played_hours,
                            "age_ic": profile.age_ic,
                        }
                        await self.db.save_player_profile(profile_dict)
                        async with self.stats_lock:
                            self.stats["found"] += 1

                found_count = len([p for p in profiles if p])
                not_found_count = len(batch_ids) - found_count
                async with self.stats_lock:
                    self.stats["not_found"] += not_found_count
                    self.stats["total_scanned"] += len(batch_ids)
                logger.info(
                    f"Worker {worker_id}: Batch {batch_index + 1} completed - Found: {found_count}, Not Found: {not_found_count}"
                )

            except Exception as e:
                if "503" in str(e):
                    async with self.stats_lock:
                        self.stats["retries_503"] += 1
                    logger.warning(
                        f"Worker {worker_id}: 503 error on batch, retrying..."
                    )
                    await asyncio.sleep(10)
                    try:
                        profiles = await scraper.batch_get_profiles(batch_ids)
                        for profile in profiles:
                            if profile:
                                profile_dict = {
                                    "player_id": profile.player_id,
                                    "player_name": profile.username,
                                    "is_online": profile.is_online,
                                    "last_connection": profile.last_seen,
                                    "faction": profile.faction,
                                    "faction_rank": profile.faction_rank,
                                    "job": profile.job,
                                    "warns": profile.warnings,
                                    "played_hours": profile.played_hours,
                                    "age_ic": profile.age_ic,
                                }
                                await self.db.save_player_profile(profile_dict)
                        async with self.stats_lock:
                            self.stats["total_scanned"] += len(batch_ids)
                    except Exception as retry_error:
                        logger.error(f"Worker {worker_id}: Retry failed: {retry_error}")
                        async with self.stats_lock:
                            self.stats["errors"] += len(batch_ids)
                else:
                    async with self.stats_lock:
                        self.stats["errors"] += len(batch_ids)
                    logger.error(f"Worker {worker_id}: Error on batch: {e}")

    async def scan_parallel(self):
        self.stats["start_time"] = datetime.now()
        self.last_progress_time = time.time()
        self.last_progress_count = 0
        start_id = self.scan_state["last_id"] + 1

        logger.info("=" * 60)
        logger.info(f"HIGHLY OPTIMIZED PARALLEL PROFILE SCANNER")
        logger.info(
            f"Range: {start_id:,} to {END_ID:,} ({END_ID - start_id + 1:,} profiles)"
        )
        logger.info(f"Workers: {self.workers} (batch processing)")
        logger.info(f"Batch Size: {BATCH_SIZE} IDs per batch")
        logger.info(
            f"Strategy: Using scraper.batch_get_profiles() for optimal parallelism"
        )
        logger.info(f"Target: 6-10 ID/s with minimal 503 errors")
        logger.info(f"Estimated Time: 8-12 hours")
        logger.info("=" * 60)

        player_ids = [str(i) for i in range(start_id, END_ID + 1)]
        all_batches = [
            player_ids[i : i + BATCH_SIZE]
            for i in range(0, len(player_ids), BATCH_SIZE)
        ]
        logger.info(f"Total batches to process: {len(all_batches)}")

        batches_per_worker = len(all_batches) // self.workers
        worker_batches = [
            all_batches[
                i * batches_per_worker : (i + 1) * batches_per_worker
                if i < self.workers - 1
                else None
            ]
            for i in range(self.workers)
        ]

        async with Pro4KingsScraper(max_concurrent=5) as scraper:
            progress_task = asyncio.create_task(self.report_progress(start_id))
            worker_tasks = [
                asyncio.create_task(self.worker(i, scraper, worker_batches[i]))
                for i in range(self.workers)
            ]

            try:
                await asyncio.gather(*worker_tasks)
            except KeyboardInterrupt:
                logger.info("\n⚠️ Scan interrupted by user")
                for task in worker_tasks:
                    task.cancel()
                progress_task.cancel()
                raise
            finally:
                progress_task.cancel()
                self.save_scan_state(start_id + self.stats["total_scanned"])

        self.stats["end_time"] = datetime.now()
        self.save_scan_state(END_ID)
        self.print_final_report()

    async def report_progress(self, start_id: int):
        last_count = 0
        last_time = datetime.now()

        while True:
            await asyncio.sleep(30)
            current_time = datetime.now()
            current_count = self.stats["total_scanned"]

            time_diff = (current_time - last_time).total_seconds()
            count_diff = current_count - last_count
            current_rate = count_diff / time_diff if time_diff > 0 else 0

            elapsed = (current_time - self.stats["start_time"]).total_seconds()
            overall_rate = current_count / elapsed if elapsed > 0 else 0

            remaining = END_ID - (start_id + current_count)
            eta_seconds = remaining / overall_rate if overall_rate > 0 else 0
            eta_hours = eta_seconds / 3600
            eta_minutes = (eta_seconds % 3600) / 60

            progress = (current_count / (END_ID - start_id + 1)) * 100
            success_rate = (
                (self.stats["found"] / current_count * 100) if current_count > 0 else 0
            )

            logger.info(
                f"""
╔════════════════════════════════════════════════════════════╗
║ PROGRESS: {progress:.1f}% ({current_count:,}/{END_ID - start_id + 1:,})
║ Found: {self.stats['found']:,} ({success_rate:.1f}%) | Not Found: {self.stats['not_found']:,}
║ Errors: {self.stats['errors']:,} | 503 Retries: {self.stats['retries_503']:,}
║
║ 📈 Performance:
║   Current Rate: {current_rate:.2f} ID/s (last 30s)
║   Average Rate: {overall_rate:.2f} ID/s (overall)
║
║ ⏱️ Time:
║   ETA: {int(eta_hours)}h {int(eta_minutes)}m
║   Elapsed: {int(elapsed/3600)}h {int((elapsed%3600)/60)}m
╚════════════════════════════════════════════════════════════╝
"""
            )

            last_count = current_count
            last_time = current_time
            self.save_scan_state(start_id + current_count)

    def print_final_report(self):
        elapsed = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        avg_rate = self.stats["total_scanned"] / elapsed if elapsed > 0 else 0
        success_rate = (
            (self.stats["found"] / self.stats["total_scanned"] * 100)
            if self.stats["total_scanned"] > 0
            else 0
        )

        logger.info("\n" + "=" * 60)
        logger.info("✅ SCAN COMPLETED!")
        logger.info("=" * 60)
        logger.info(
            f"""
📊 Statistics:
  Total Scanned: {self.stats['total_scanned']:,}
  Found (exists): {self.stats['found']:,} ({success_rate:.1f}%)
  Not Found (404): {self.stats['not_found']:,}
  Errors: {self.stats['errors']:,}
  503 Retries: {self.stats['retries_503']:,}

⏱️ Performance:
  Duration: {int(elapsed/3600)}h {int((elapsed%3600)/60)}m
  Average Rate: {avg_rate:.2f} profiles/sec
  Target Rate: 6-10 ID/s
  Status: {'✅ EXCELLENT' if avg_rate >= 6 else '⚠️ BELOW TARGET'}

💾 Database:
  Total profiles stored: {self.stats['found']:,}
"""
        )


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Optimized scanner for Pro4Kings profiles"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=CONCURRENT_WORKERS,
        help=f"Number of concurrent workers (default: {CONCURRENT_WORKERS})",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reset scan state and start from ID 1"
    )
    args = parser.parse_args()

    if args.reset and os.path.exists(SCAN_STATE_FILE):
        os.remove(SCAN_STATE_FILE)
        logger.info("Scan state reset")

    scanner = FastScanner(workers=args.workers)
    try:
        await scanner.scan_parallel()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️ Scan interrupted - progress saved")
        logger.info(f"Run again to resume from ID {scanner.scan_state['last_id']}")
    except Exception as e:
        logger.error(f"\n\n❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
