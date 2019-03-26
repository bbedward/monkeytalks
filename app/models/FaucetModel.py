import datetime
import redis
import peewee

from flask import current_app

from app.database import db
from app.util.validations import Validations
from app.util.rpc import RPC
from app.util.conversions import BananoConversions

rd = redis.Redis()

class FaucetPayment(db.Model):
    destination = peewee.CharField(max_length=64, index=True)
    block_hash = peewee.CharField(max_length=64)
    created_at = peewee.DateTimeField(default=datetime.datetime.now(), index=True)
    ip_address = peewee.CharField(index=True)

    class Meta:
        db_table = 'faucet_payments'

    @classmethod
    def make_or_reject_payment(cls, account : str, ip: str) -> tuple:
        account = Validations.get_banano_address(account)
        if account is None or Validations.validate_address(account) == False:
            return (None, "That doesn't look like a valid BANANO address")
        # Block to prevent concurrent requests
        with rd.lock(account, timeout=300, blocking_timeout=60):
            # Check recent payments
            payment_24h = (cls.select()
                        .where(((FaucetPayment.destination == account) | (FaucetPayment.ip_address == ip)) 
                            & FaucetPayment.created_at > (datetime.datetime.utcnow() - datetime.timedelta(days=1))))
            for payment in payment_24h:
                next_available = datetime.datetime.utcnow() - payment.created_at
                diff_minutes = next_available.seconds // 60
                return (None, f"You've already stocked up recently - why don't you come back in {diff_minutes} minutes?")
            # Calculate payment amount in raw
            rpc = RPC()
            balance = rpc.account_balance(current_app.config['MONKEYTALKS_ACCOUNT'])
            if balance is None:
                return (None, "This is embarassing...we have a problem on our end - please try again later!")
            payment_amount = balance * current_app.config['PAYOUT_FACTOR'] # A portion of our balance
            # Be good guys and don't send out odd raw amounts, this trims it. e.g. 10.034566 BANANO = 10.03 BANANO
            payment_amount = BananoConversions.banano_to_raw(BananoConversions.raw_to_banano(payment_amount))
            if int(payment_amount == 0):
                return (None, "We're all out of potassium. Send some messages to fill us up again.")
            # Actually make the payment
            hash = rpc.send(account, str(payment_amount))
            payment_record = FaucetPayment(
                destination = account,
                ip_address = ip,
                block_hash = hash,
                created_at = datetime.datetime.utcnow()
            )
            payment_record.save()
            return (payment_record, f"Congratulations! You've been sent {BananoConversions.raw_to_banano(payment_amount)} BANANO!")