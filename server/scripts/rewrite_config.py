import sys
import warnings

import structlog
import typer
from sqlalchemy import exc as sa_exc

from server.db import db, init_database, transactional
from server.db.models import ShopTable
from server.schemas.shop import ConfigurationV1
from server.settings import app_settings

logger = structlog.get_logger(__name__)


def get_new_config(config: dict) -> ConfigurationV1 | None:
    try:
        return ConfigurationV1(**config)
    except Exception:
        return None


def rewrite_all_shop_config(dry_run: bool):
    shops = db.session.query(ShopTable).all()
    if not shops:
        sys.exit("No shops found")
    if dry_run:
        logger.info("Dry run enabled, not rewriting all shop config")
    with transactional(db, logger):
        for shop in shops:
            old_config_dict = shop.config

            new_config = get_new_config(old_config_dict)
            if not new_config:
                logger.warning("Shop Config parse failed, skipping", shop=shop.name, id=shop.id)
            elif new_config.model_dump() != old_config_dict:
                from deepdiff import DeepDiff

                diff = DeepDiff(old_config_dict, new_config.model_dump())
                logger.info("Changes detected in Shop Config", shop=shop.name, id=shop.id, diff=diff)
            else:
                logger.info("No Changes detected in Shop Config, everything OK.", shop=shop.name, id=shop.id)


app = typer.Typer()


@app.command()
def main(
    dry_run: bool = typer.Option(
        True, help="Disable to actually mutate stuff in the DB, otherwise print only what will be done."
    ),
):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=sa_exc.SAWarning)
        rewrite_all_shop_config(dry_run=dry_run)


if __name__ == "__main__":
    init_database(app_settings)
    app()
