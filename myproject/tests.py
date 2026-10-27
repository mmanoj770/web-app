from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from myproject.settings import _database_from_url


class DatabaseUrlTests(SimpleTestCase):
    def test_postgres_url(self):
        db = _database_from_url('postgresql://mj:p%40ss@ep-1.neon.tech:5432/store?sslmode=require')
        self.assertEqual(db['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual((db['USER'], db['PASSWORD'], db['HOST'], db['PORT'], db['NAME']),
                         ('mj', 'p@ss', 'ep-1.neon.tech', '5432', 'store'))
        self.assertEqual(db['OPTIONS'], {'sslmode': 'require'})

    def test_defaults_to_ssl(self):
        self.assertEqual(_database_from_url('postgres://u:p@host/db')['OPTIONS']['sslmode'], 'require')

    def test_rejects_other_databases(self):
        with self.assertRaises(ImproperlyConfigured):
            _database_from_url('mysql://u:p@host/db')
