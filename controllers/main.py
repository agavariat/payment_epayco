# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging
import pprint
import sys
import requests
import werkzeug
from odoo import http
from odoo.http import request, Response
from werkzeug import urls

_logger = logging.getLogger(__name__)


class EpaycoController(http.Controller):
    @http.route(['/payment/epayco/checkout'], type='http', website=True, csrf=False)
    def epayco_return(self, **post):
        """ Epayco."""
        order = request.website.sale_get_order()
        post_data = {
            'amount_tax': order.amount_tax,
            'amount_untaxed': order.amount_untaxed,
        }
        post.update(post_data)
        return request.render('payment_epayco.checkout', post)

    @http.route(['/payment/epayco/response/'], type='http', website=True, csrf=False)
    def epayco_return_url(self, **post):
        """Process response from ePayco after process payment."""
        return self._epayco_process_response(post)

    @http.route(
        ['/payment/epayco/confirmation/'],
        type='http',
        csrf=False,
        website=True,
        auth='public')
    def epayco_payment_confirmation_url(self, **post):
        """Process payment confirmation from ePayco."""
        return self._epayco_process_response(post, confirmation=True)

    def _epayco_process_response(self, data, confirmation=False):
        if not confirmation:
            ref_payco = data.get('ref_payco')
            if ref_payco is None:
                _logger.debug('User error in ePayco checkout: %s', data)
                return werkzeug.utils.redirect('/shop/payment')
            url = 'https://secure.epayco.co/validation/v1/reference/%s' % (
                ref_payco)
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json().get('data')
                request.env['payment.transaction'].sudo().form_feedback(data, 'epayco')
                return werkzeug.utils.redirect('/payment/process')
            #_logger.warning('ePayco: Request to API ePayco failed.')
        else:
            request.env['payment.transaction'].sudo().form_feedback(
                data, 'epayco')
            return False