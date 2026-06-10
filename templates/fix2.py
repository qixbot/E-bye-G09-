import psycopg2
conn = psycopg2.connect('postgresql://neondb_owner:npg_9GZaIxBEz2hp@ep-dawn-haze-aohd5pn2-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require')
cur = conn.cursor()
cur.execute('UPDATE offers SET product_id = 1 WHERE id = 1')
conn.commit()
print('Done')
conn.close()