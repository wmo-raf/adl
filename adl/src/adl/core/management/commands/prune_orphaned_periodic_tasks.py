from django.core.management.base import BaseCommand

from adl.core.tasks import prune_orphaned_periodic_tasks


class Command(BaseCommand):
    help = (
        "Remove beat schedule entries for network connections and dispatch "
        "channels that no longer exist. New deletes are cleaned up by signal; "
        "this is for orphans a deployment accumulated before that existed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List the orphaned entries without deleting them',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        orphans = prune_orphaned_periodic_tasks(dry_run=dry_run)

        if not orphans:
            self.stdout.write(self.style.SUCCESS("No orphaned schedule entries found."))
            return

        # The delete has already happened by this point, so the listing is a
        # record of what went, not a preview of what will
        self.stdout.write("Would remove:" if dry_run else "Removed:")

        for entry in orphans:
            self.stdout.write(f"  {entry.task} args={entry.args} (name={entry.name})")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN - {len(orphans)} entries would be removed. No changes made."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"\nRemoved {len(orphans)} orphaned schedule entries."
        ))
