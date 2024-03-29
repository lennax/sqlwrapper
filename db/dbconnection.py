import datetime
import json
import decimal


class JSONCustomEncoder(json.JSONEncoder):

    """Encodes dates with ISO formatting"""

    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat(' ')
        else:
            return json.JSONEncoder.default(self, obj)


class Query(object):

    def __init__(self, sql):
        self.sql = sql
        self.start_time = None
        self.end_time = None
        self.error = None

    def __str__(self):
        return self.sql

    def exec_select(self, conn, return_type='dict'):
        """
        Returns the value of the SQL as a generator as either a dict or result
        set.

        """
        self.start_time = datetime.datetime.now()
        try:
            curs = conn.cursor()
            curs.execute(self.sql)
            self.end_time = datetime.datetime.now()

            cols = [x[0].lower() for x in curs.description]
            while(True):
                results = curs.fetchmany(25)
                if not results:
                    break
                for r in results:
                    if return_type == 'dict':
                        yield dict(zip(cols, r))
                    if return_type == 'rset':
                        yield r
        except Exception, e:
            self.end_time = datetime.datetime.now()
            self.error_text = str(e)
            raise e

    def exec_select_json(self, conn):
        """ Turns a result set into a JSON object.
        Output looks like this:
        {
            "rows": [[17, "Cally's War (Posleen War Series #5)", "John Ringo, Julie Cochrane", "141652052X", "Baen"],
                    [19, "Last Chance to See", "Douglas Adams, Mark Carwardine", "0345371984", "Ballantine Books"],
                    [20, "Dirk Gently's Holistic Detective Agency", "Douglas Adams", "0671746723", "Pocket"],
                    [21, "The Long Dark Tea-Time of the Soul", "Douglas Adams", "0671742515", "Pocket Books"],
                    [26, "So Long, and Thanks for All the Fish", "Douglas Adams", "0345479963", "Del Rey"]],
            "total_rows": 5,
            "run_time": "0.002321",
            "run_date": "2010-11-06T15:59:21.810127",
            "sql": "select id, title, author, asin, publisher from library_books limit 5",
            "columns": ["id", "title", "author", "asin", "publisher"]
        }
        """

        curs = conn.cursor()
        self.start_time = datetime.datetime.now()
        query = {"sql": self.sql, "run_date": self.start_time}
        try:
            curs.execute(self.sql)
            self.end_time = datetime.datetime.now()

            columns = [i[0] for i in curs.description]
            rows = []

            row = curs.fetchone()
            while row:
                rows.append(row)
                row = curs.fetchone()

            query["columns"] = columns
            query["rows"] = rows
            query["run_date"] = self.end_time
            query["run_time"] = self.delta_to_seconds(self.end_time
                                                      - self.start_time)
            query["total_rows"] = curs.rowcount

            x = json.dumps(query, cls=JSONCustomEncoder)

            return x

        except Exception, e:
            self.error = str(e)
            self.end_time = datetime.datetime.now()

            raise e

    def exec_update(self, conn):
        self.start_time = datetime.datetime.now()
        try:
            curs = conn.cursor()
            curs.execute(self.sql)
            self.end_time = datetime.datetime.now()

            return curs.rowcount
        except Exception, e:
            self.end_time = datetime.datetime.now()
            self.error = str(e)
            raise e

    @staticmethod
    def bind(a, where=0):
        if a is None:
            a_list = ['null']
            connector = "is "
        else:
            a_list = ["'", str(a).replace("'", "''"), "'"]
            connector = "= "
        if where:
            a_list.insert(0, connector)
        return "".join(a_list)

    @staticmethod
    def delta_to_seconds(dt):
        d = decimal.Decimal(dt.days * 24 * 3600)
        d = d + dt.seconds
        d = d + (decimal.Decimal(dt.microseconds) / 1000000)

        return str(d)


class DBConnection(object):

    def __init__(self, conn):
        self.conn = conn
        self.query_list = []

    def __str__(self):
        return str(self.conn)

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        return self.conn.close()

    def select(self, from_clause, where=None, order=None,
               select_list=None, return_type='dict'):
        select_clause = " * "
        if select_list:
            select_clause = ", ".join(select_list)

        order_by_clause = ""
        if order:
            order_by_clause = " order by " + order

        query = "select %s from %s %s %s" % (select_clause, from_clause,
                                             self.where_clause(where),
                                             order_by_clause)
        q = Query(query)
        self.query_list.append(q)

        if return_type == 'json':
            return q.exec_select_json(self.conn)
        else:
            return q.exec_select(self.conn, return_type)

    def select_sql(self, sql, return_type='dict'):
        q = Query(sql)
        self.query_list.append(q)
        if return_type == 'json':
            return q.exec_select_json(self.conn)
        else:
            return q.exec_select(self.conn, return_type)

    def update(self, from_clause, set_list=None, where=None):
        set_clause = ", ".join(["%s = %s" % (k, Query.bind(v))
                                for k, v in set_list.iteritems()])

        query = "update %s set %s %s" % (from_clause, set_clause,
                                         self.where_clause(where))
        q = Query(query)
        self.query_list.append(q)

        return q.exec_update(self.conn)

    def update_sql(self, sql):
        q = Query(sql)
        self.query_list.append(q)

        return q.exec_update(self.conn)

    def insert(self, from_clause, columns=None):
        column_list = ", ".join(columns.keys())
        value_list = ", ".join([Query.bind(v) for v in columns.values()])
        query = "insert into %s (%s) values (%s)" % (from_clause,
                                                     column_list, value_list)
        q = Query(query)
        self.query_list.append(q)

        return q.exec_update(self.conn)

    def upsert(self, from_clause, set_list, where):
        x = self.update(from_clause, set_list, where)
        if x == 0 and isinstance(where, dict):
            x = self.insert(from_clause, set_list.update(where))
        elif x == 0:
            x = self.insert(from_clause, set_list)
        return x

    def delete(self, from_clause, where):
        query = "delete from %s %s" % (from_clause, self.where_clause(where))
        q = Query(query)
        self.query_list.append(q)

        return q.exec_update(self.conn)

    def get_or_insert(self, table, ident_dict, id=None):
        """Get or insert id from given table"""
        id_val = self.get_existing_value(table, ident_dict, id)
        if id_val is None:
            self.insert(table, ident_dict)
            id_val = self.get_existing_value(table, ident_dict, id)
        assert id_val, ident_dict
        return id_val

    def get_existing_value(self, table, ident_dict, id=None):
        """Get existing id for given table identifier"""
        if id is None:
            id = table + "id"
        ret = self.select(from_clause=table, select_list = [id],
                             where=ident_dict)
        ret = list(ret)
        nrow = len(ret)
        if nrow > 1:
            assert False, nrow
        elif nrow == 1:
            return ret[0][id]
        # Default return of None indicates value is missing

    @staticmethod
    def where_clause(where):
        if not where:
            return ""

        if isinstance(where, dict):
            return " where " + " and ".join(["%s %s" % (k, Query.bind(v, where=1))
                                             for k, v in where.iteritems()])

        if isinstance(where, basestring):
            return " where " + where

    @staticmethod
    def in_clause(col, where):
        return "%s in ('%s')" % (col, "', '".join(where))
