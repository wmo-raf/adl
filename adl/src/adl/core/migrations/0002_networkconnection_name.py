# Generated by Django 5.0.6 on 2024-11-28 19:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='networkconnection',
            name='name',
            field=models.CharField(default='FTP', max_length=255, verbose_name='Name'),
            preserve_default=False,
        ),
    ]
