from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_users_created_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='date_of_birth',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customer',
            name='nominee',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='customer',
            name='occupation',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='customer',
            name='permanent_address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='customer',
            name='pin_code',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
        migrations.AddField(
            model_name='customer',
            name='present_address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='customer',
            name='relationship',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='customer',
            name='aadhar_number',
            field=models.CharField(blank=True, default='', max_length=12),
        ),
    ]
