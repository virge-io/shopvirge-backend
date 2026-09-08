import warnings

import structlog
import typer
from sqlalchemy import exc as sa_exc

from server.db import db, init_database, transactional
from server.db.models import Account
from server.db.models import OrderTable as Order
from server.settings import app_settings

logger = structlog.get_logger(__name__)


def get_accounts_with_missing_details():
    return db.session.query(Account).filter(Account.details == None)


def get_orders_for_accounts(accounts: list[Account]):
    account_ids = (account.id for account in accounts)
    return db.session.query(Order).filter(Order.account_id.in_(account_ids))


def cleanup_accounts_and_orders(dry_run: bool = False):
    logger.info("Cleaning up accounts with no details")

    with transactional(db, logger):
        accounts_with_no_details = get_accounts_with_missing_details().all()
        orders_query = get_orders_for_accounts(accounts_with_no_details)

        if dry_run:
            logger.info("Showing planned changes")
            logger.info(f"Accounts to be deleted: {accounts_with_no_details}")
            logger.info(f"Orders to be deleted: {orders_query.all()}")
            return

        logger.info("Deleting accounts with no details and corresponding orders")
        orders_deleted = orders_query.delete()
        accounts_deleted = get_accounts_with_missing_details().delete()

    logger.info("Cleanup of accounts finished", accounts_deleted=accounts_deleted, orders_deleted=orders_deleted)


app = typer.Typer()


@app.command()
def main(
    dry_run: bool = typer.Option(
        True, help="Disable to actually mutate stuff in the DB, otherwise print only what will be done.", is_flag=True
    ),
):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=sa_exc.SAWarning)
        cleanup_accounts_and_orders(dry_run=dry_run)


if __name__ == "__main__":
    init_database(app_settings)
    app()
