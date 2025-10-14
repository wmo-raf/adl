from django.core.management.base import BaseCommand
from django.db import connection
from datetime import datetime

class Command(BaseCommand):
    help = 'Refresh hourly aggregate for all historical data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date (YYYY-MM-DD HH:MM:SS). Default: earliest observation',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date (YYYY-MM-DD HH:MM:SS). Default: now',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be refreshed without actually doing it',
        )
    
    def handle(self, *args, **options):
        start_date = options.get('start_date')
        end_date = options.get('end_date')
        dry_run = options.get('dry_run', False)
        
        with connection.cursor() as cursor:
            # Get date range info
            if not start_date:
                cursor.execute("""
                    SELECT MIN(time) FROM core_observationrecord WHERE is_daily = false;
                """)
                result = cursor.fetchone()
                start_date = result[0] if result[0] else datetime.now()
            
            if not end_date:
                end_date = datetime.now()
            
            # Get record counts
            cursor.execute("""
                SELECT COUNT(*) FROM core_observationrecord
                WHERE is_daily = false AND time BETWEEN %s AND %s;
            """, [start_date, end_date])
            raw_count = cursor.fetchone()[0]
            
            self.stdout.write(f"\nDate range: {start_date} to {end_date}")
            self.stdout.write(f"Raw observations to aggregate: {raw_count:,}")
            
            if dry_run:
                self.stdout.write(self.style.WARNING("\nDRY RUN - No changes made"))
                return
            
            # Confirm for large datasets
            if raw_count > 1_000_000:
                self.stdout.write(self.style.WARNING(
                    f"\nThis will process {raw_count:,} records. This may take a while."
                ))
                response = input("Continue? (yes/no): ")
                if response.lower() != 'yes':
                    self.stdout.write("Aborted.")
                    return
            
            # Do the refresh
            self.stdout.write("\nRefreshing aggregate... ", ending='')
            self.stdout.flush()
            
            start_time = datetime.now()
            cursor.execute("""
                CALL refresh_continuous_aggregate('obs_agg_1h', %s, %s);
            """, [start_date, end_date])
            duration = (datetime.now() - start_time).total_seconds()
            
            # Get result counts
            cursor.execute("""
                SELECT COUNT(*) FROM obs_agg_1h
                WHERE bucket BETWEEN %s AND %s;
            """, [start_date, end_date])
            agg_count = cursor.fetchone()[0]
            
            self.stdout.write(self.style.SUCCESS(f"Done! ({duration:.1f}s)"))
            self.stdout.write(f"Aggregated records created: {agg_count:,}")
            self.stdout.write(f"Compression ratio: {raw_count/agg_count if agg_count else 0:.1f}x\n")