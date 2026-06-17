# Copyright 2015 ADHOC SA  (http://www.adhoc.com.ar)
# Copyright 2017 - 2019 Alex Comba - Agile Business Group
# Copyright 2017 Tecnativa - David Vidal
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_report_rows(self):
        rows = super()._get_report_rows()
        pack_lines = self.order_line.filtered(
            lambda line: line.product_id.pack_ok
        ).sorted(key=lambda line: line.id)
        pack_index = 0
        for row in rows:
            if row["is_pack"]:
                line = (
                    pack_lines[pack_index]
                    if pack_index < len(pack_lines)
                    else self.env["sale.order.line"]
                )
                pack_index += 1
            else:
                line = self.order_line.filtered(
                    lambda order_line, tmpl=row["tmpl"]: (
                        not order_line.product_id.pack_ok
                        and order_line.product_id.product_tmpl_id == tmpl
                    )
                )[:1]
            row.update(
                {
                    "discount1": line.discount1 if line else 0.0,
                    "discount2": line.discount2 if line else 0.0,
                    "discount3": line.discount3 if line else 0.0,
                }
            )
        return rows
