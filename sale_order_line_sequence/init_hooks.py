# Copyright 2017 Eficent Business and IT Consulting Services S.L.
# Copyright 2017 Serpent Consulting Services Pvt. Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from openupgradelib import openupgrade
from odoo import api, SUPERUSER_ID
from odoo.api import Environment


fields2add = [
    (
        "max_line_sequence",
        "sale.order",
        "sale_order",
        "integer",
        False,
        "sale_order_line_sequence",
    ),
    (
        "sequence2",
        "sale.order.line",
        "sale_order_line",
        "integer",
        False,
        "sale_order_line_sequence",
    ),
]


def post_init_hook(cr, pool):
    """
    Fetches all the sale order and resets the sequence of the order lines
    """
    env = Environment(cr, SUPERUSER_ID, {})
    sale = env['sale.order'].search([])
    sale._reset_sequence()


def pre_init_hook(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    openupgrade.add_fields(env, fields2add)
