from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0020_cancelledplot_closure_status_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='IncentiveWithdrawalRequest',
            fields=[
                ('iwr_id', models.AutoField(primary_key=True, serialize=False)),
                ('role', models.CharField(choices=[('manager', 'Manager'), ('executive', 'Executive'), ('telecaller', 'Telecaller'), ('accounts', 'Accounts')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], default='PENDING', max_length=20)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('remarks', models.TextField(blank=True)),
                ('processed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='processed_incentive_withdrawals', to='accounts.users', db_column='processed_by')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='incentive_withdrawal_requests', to='accounts.users', db_column='requested_by')),
            ],
            options={
                'db_table': 'incentive_withdrawal_request',
                'ordering': ['-requested_at'],
            },
        ),
    ]
