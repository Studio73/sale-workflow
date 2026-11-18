# Copyright 2017 Omar Castiñeira, Comunitea Servicios Tecnológicos S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"

    account_payment_ids = fields.One2many(
        comodel_name="account.payment",
        inverse_name="sale_id",
        string="Pay sale advanced",
    )
    amount_residual = fields.Float(
        string="Residual amount",
        compute="_compute_advance_payment",
        store=True,
    )
    payment_line_ids = fields.Many2many(
        comodel_name="account.move.line",
        string="Payment move lines",
        compute="_compute_advance_payment",
        store=True,
    )
    advance_payment_status = fields.Selection(
        selection=[
            ("not_paid", "Not Paid"),
            ("paid", "Paid"),
            ("partial", "Partially Paid"),
        ],
        store=True,
        copy=False,
        tracking=True,
        compute="_compute_advance_payment",
    )

    @api.depends(
        "currency_id",
        "company_id",
        "amount_total",
        "account_payment_ids",
        "account_payment_ids.state",
        "account_payment_ids.move_id",
        "account_payment_ids.move_id.line_ids",
        "account_payment_ids.move_id.line_ids.date",
        "account_payment_ids.move_id.line_ids.debit",
        "account_payment_ids.move_id.line_ids.credit",
        "account_payment_ids.move_id.line_ids.currency_id",
        "account_payment_ids.move_id.line_ids.amount_currency",
        "account_payment_ids.move_id.line_ids.amount_residual",
        "account_payment_ids.move_id.line_ids.amount_residual_currency",
        "invoice_ids.amount_residual",
        "invoice_ids.amount_total",
        "invoice_ids.state",
        "invoice_ids.move_type",
        "invoice_ids.currency_id",
        "invoice_ids.invoice_date",
        "invoice_ids.date",
        "invoice_ids.invoice_line_ids.price_total",
        "invoice_ids.invoice_line_ids.sale_line_ids.order_id",
        "invoice_ids.invoice_line_ids.sale_line_ids.price_total",
        "invoice_ids.invoice_line_ids.sale_line_ids.currency_id",
    )
    def _compute_advance_payment(self):
        invoice_allocations = {}
        for order in self:
            mls = order.account_payment_ids.mapped("move_id.line_ids").filtered(
                lambda x: x.account_id.account_type == "asset_receivable"
                and x.parent_state == "posted"
            )
            advance_amount = 0.0
            for line in mls:
                line_currency = line.currency_id or line.company_id.currency_id
                # Exclude reconciled pre-payments amount because once reconciled
                # the pre-payment will reduce invoice residual amount like any
                # other payment.
                line_amount = (
                    line.amount_residual_currency
                    if line.currency_id
                    else line.amount_residual
                )
                line_amount *= -1
                if line_currency != order.currency_id:
                    advance_amount += line.currency_id._convert(
                        line_amount,
                        order.currency_id,
                        order.company_id,
                        line.date or fields.Date.today(),
                    )
                else:
                    advance_amount += line_amount
            # Consider payments in related invoices.
            invoice_paid_amount = 0.0
            for inv in order.invoice_ids.filtered(lambda m: m.state == "posted"):
                if inv.id not in invoice_allocations:
                    invoice_allocations[inv.id] = self._allocate_invoice_payment(inv)
                paid = invoice_allocations[inv.id].get(order.id, 0.0)
                if inv.move_type == "out_refund":
                    paid = -paid
                if inv.currency_id != order.currency_id:
                    paid = inv.currency_id._convert(
                        paid,
                        order.currency_id,
                        order.company_id,
                        inv.invoice_date or inv.date or fields.Date.today(),
                    )
                invoice_paid_amount += paid

            amount_residual = order.amount_total - advance_amount - invoice_paid_amount
            payment_state = "not_paid"
            if mls:
                has_due_amount = float_compare(
                    amount_residual, 0.0, precision_rounding=order.currency_id.rounding
                )
                if has_due_amount <= 0:
                    payment_state = "paid"
                elif has_due_amount > 0:
                    payment_state = "partial"
            order.payment_line_ids = mls
            order.amount_residual = amount_residual
            order.advance_payment_status = payment_state

    def _allocate_invoice_payment(self, invoice):
        """Allocate a payment proportionally to invoice lines and sales orders.

        Invoice lines without a sales order retain their own share. When a line
        refers to several orders, their sales-line totals are the available
        weights; the actual intended split is not recorded on the invoice.
        """
        currency = invoice.currency_id
        if currency.is_zero(invoice.amount_total):
            return {}

        amounts_by_order = {}
        for line in invoice.invoice_line_ids:
            weights = {}
            for sale_line in line.sale_line_ids:
                amount = abs(sale_line.price_total)
                if sale_line.currency_id != currency:
                    amount = sale_line.currency_id._convert(
                        amount,
                        currency,
                        invoice.company_id,
                        invoice.invoice_date or invoice.date or fields.Date.today(),
                        round=False,
                    )
                order_id = sale_line.order_id.id
                weights[order_id] = weights.get(order_id, 0.0) + amount
            if not weights:
                continue
            total_weight = sum(weights.values())
            if currency.is_zero(total_weight):
                weights = dict.fromkeys(weights, 1.0)
                total_weight = len(weights)
            for order_id, weight in weights.items():
                amounts_by_order[order_id] = amounts_by_order.get(order_id, 0.0) + (
                    line.price_total * weight / total_weight
                )

        # Keep unlinked lines and any difference in the invoice total separate,
        # so their payment is not assigned to the linked orders.
        unassigned = invoice.amount_total - sum(amounts_by_order.values())
        buckets = dict(amounts_by_order)
        if not currency.is_zero(unassigned):
            buckets[None] = unassigned
        if not buckets:
            return {}

        paid = invoice.amount_total - invoice.amount_residual
        allocations = {
            order_id: currency.round(paid * amount / invoice.amount_total)
            for order_id, amount in buckets.items()
        }
        # Assign rounding differences deterministically, including unlinked
        # amounts, so allocated cents add up to the payment on this invoice.
        difference = currency.round(paid - sum(allocations.values()))
        if not currency.is_zero(difference):
            target = min(buckets, key=lambda key: (-abs(buckets[key]), key or 0))
            allocations[target] = currency.round(allocations[target] + difference)
        allocations.pop(None, None)
        return allocations

    def _has_to_be_paid(self):
        # If an order 'has to be paid' it will show the "Accept & Pay" button in the
        # portal. This prevents that, as you do't want customers payign for orders that
        # are already paid
        res = super()._has_to_be_paid()
        return res and self.amount_residual > 0
