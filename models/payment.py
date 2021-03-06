# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import hashlib
import uuid
import sys
import pprint

from werkzeug import urls

from odoo import api, fields, models, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.tools.float_utils import float_compare
import logging
_logger = logging.getLogger(__name__)

class PaymentAcquirerEpayco(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('epayco', 'Epayco')])
    epayco_p_cust_id = fields.Char(string='P_CUST_ID', required_if_provider='epayco', groups='base.group_user')
    epayco_p_key = fields.Char(string='P_KEY', required_if_provider='epayco', groups='base.group_user')
    epayco_public_key = fields.Char(string='PUBLICK_KEY', required_if_provider='epayco', groups='base.group_user')
    epayco_checkout = fields.Boolean('One page Checkout', default=True, help='One page Checkou',
                                    groups='base.group_user')
    epayco_checkout_type = fields.Selection(
        selection=[('onpage', 'Onpage Checkout'),
                   ('standard', 'Standard Checkout')],
        required_if_provider='epayco',
        string='Checkout Type',
        default='onpage')

    def epayco_form_generate_values(self, values):
        self.ensure_one()
        env_test = 'false' if self.environment == 'prod' else 'true'
        partner_lang = values.get('partner') and values['partner'].lang
        lang = 'es' if 'es' in partner_lang else 'en'
        epayco_checkout = 'false' if self.epayco_checkout == False else 'true'
        country = values.get('partner_country').code.lower()
        epayco_checkout_external = (
            'false' if self.epayco_checkout_type == 'onpage' else 'true')
        tx = self.env['payment.transaction'].search([('reference', '=', values.get('reference'))])
        #if tx.state not in ['done', 'pending']:
            #tx.reference = str(uuid.uuid4())
        base_url = self.get_base_url()
        url_confirmation = urls.url_join(base_url, '/payment/epayco/confirmation/')
        url_response = urls.url_join(base_url, '/payment/epayco/response/')
        epayco_tx_values = dict(values)
        split_reference = epayco_tx_values.get('reference').split('-')
        order = ''
        if split_reference:
            order = split_reference[0]
        epayco_tx_values.update({
            'public_key': self.epayco_public_key,
            'txnid': values['reference'],
            'amount': values['amount'],
            #'productinfo': tx.reference,
            'productinfo': values['reference'],
            'firstname': values.get('partner_name'),
            'email': values.get('partner_email'),
            'phone': values.get('partner_phone'),
            'currency_code': values['currency'] and values['currency'].name or '',
            'country_code': country,
            'epayco_checkout_external': epayco_checkout,
            'epayco_env_test': env_test,
            'epayco_lang': lang,
            'response_url': url_response,
            'url_confirmation': url_confirmation,
            'extra1': order,
            'extra2': values['reference'],
            'extra3': epayco_tx_values.get('reference'),
        })

        return epayco_tx_values

    def epayco_get_form_action_url(self):
        self.ensure_one()
        return '/payment/epayco/checkout/'

    def _epayco_generate_sign(self, values):
        """ Generate the shasign for incoming or outgoing communications.
        :param self: the self browse record. It should have a shakey in shakey out
        :param string inout: 'in' (odoo contacting epayco) or 'out' (epayco
                             contacting odoo).
        :param dict values: transaction values
        :return string: shasign
        """
        self.ensure_one()
        p_key = self.epayco_p_key
        p_cust_id = self.epayco_p_cust_id
        x_ref_payco = values.get('x_ref_payco')
        x_transaction_id = values.get('x_transaction_id')
        x_amount = values.get('x_amount')
        x_currency_code = values.get('x_currency_code')

        hash_str_bytes = bytes('%s^%s^%s^%s^%s^%s' % (
            p_cust_id,
            p_key,
            x_ref_payco,
            x_transaction_id,
            x_amount,
            x_currency_code), 'utf-8')
        hash_object = hashlib.sha256(hash_str_bytes)
        hash = hash_object.hexdigest()
        return hash

class PaymentTransactionEpayco(models.Model):
    _inherit = 'payment.transaction'


    def _get_processing_info(self):
        res = super()._get_processing_info()
        if self.acquirer_id.provider == 'epayco':
            epayco_info = {
                'epayco_p_cust_id': self.acquirer_id.epayco_p_cust_id,
            }
            res.update(epayco_info)
        return res

    def form_feedback(self, data, acquirer_name):
        if data.get("x_ref_payco") and acquirer_name == "epayco":
            data.update(data)
            _logger.info(
                "Epayco: entering form_feedback with post data %s"
                % pprint.pformat(data)
            )
        return super(PaymentTransactionEpayco, self).form_feedback(data, acquirer_name)


    @api.model
    def _epayco_form_get_tx_from_data(self, data):
        """ Given a data dict coming from epayco, verify it and find the related
        transaction record. """
        reference = data.get('x_extra4')
        #reference = data.get('x_id_factura')
        signature = data.get('x_signature')
        if not reference or not reference or not signature:
            raise ValidationError(_('Epayco: received data with missing reference (%s) or signature (%s)') % (reference, signature))

        transaction = self.search([('reference', '=', reference)])
        if not transaction:
            error_msg = (_('Epayco: received data for reference %s; no order found') % (reference))
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        elif len(transaction) > 1:
            error_msg = (_('Epayco: received data for reference %s; multiple orders found') % (reference))
            _logger.error(error_msg)
            raise ValidationError(error_msg)


        #verify signature
        shasign_check = transaction.acquirer_id._epayco_generate_sign(data)

        if shasign_check != signature:
            raise ValidationError(_('Epayco: invalid signature, received %s, computed %s, for data %s') % (signature, shasign_check, data))

        return transaction


    def _epayco_form_get_invalid_parameters(self, data):
        invalid_parameters = []

        #check what is buyed
        if int(self.acquirer_id.epayco_p_cust_id) != int(data.get('x_cust_id_cliente')):
            invalid_parameters.append(
                ('Customer ID', data.get('x_cust_id_cliente'), self.acquirer_id.epayco_p_cust_id))

        return invalid_parameters

    @api.multi
    def _epayco_form_validate(self, data):
        status = data.get('x_transaction_state')
        #sys.exit()
        result = self.write({
            'acquirer_reference': data.get('x_ref_payco'),
            'date': fields.Datetime.now(),
        })
        if status == 'Aceptada':
            self._set_transaction_done()
        elif status == 'Pendiente':
            self._set_transaction_pending()
        else:
            self._set_transaction_cancel()
        return result