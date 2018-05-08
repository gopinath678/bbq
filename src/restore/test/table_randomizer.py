import logging
import random
from datetime import datetime, timedelta

from commons.decorators.retry import retry
from src.big_query.big_query import BigQuery, RandomizationError
from src.big_query.big_query_table_metadata import BigQueryTableMetadata


class DoesNotMeetSampleCriteriaException(BaseException):
    pass


class TableRandomizer(object):

    def __init__(self):
        self.big_query = BigQuery()

    @retry((RandomizationError, DoesNotMeetSampleCriteriaException),
           tries=10, delay=0, backoff=0)
    def get_random_table_metadata(self):
        table_reference = self.big_query.fetch_random_table()
        logging.info("Randomly selected table for the restore test: %s",
                     table_reference)

        project_id = table_reference.get_project_id()
        dataset_id = table_reference.get_dataset_id()
        table_id = table_reference.get_table_id()

        table_metadata_payload = self.big_query.get_table(project_id,
                                                          dataset_id,
                                                          table_id,
                                                          log_table=False)

        if table_metadata_payload is None:
            raise DoesNotMeetSampleCriteriaException("Table not found")

        table_metadata = BigQueryTableMetadata(table_metadata_payload)

        if table_metadata.is_external_or_view_type():
            raise DoesNotMeetSampleCriteriaException(
                "Table is a view or external.")

        if self.__has_been_modified_since_midnight(table_metadata):
            raise DoesNotMeetSampleCriteriaException(
                "Table has been modified since midnight")

        if self.__was_modified_yesterday(table_metadata):
            logging.error("Table was modified yesterday. "
                          "It is possible that last backup cycle did not cover"
                          " it. Therefore restoration of this table can fail.")

        if table_metadata.is_daily_partitioned() and not table_metadata.is_empty():
            table_metadata = self.__get_random_partition(dataset_id,
                                                         project_id,
                                                         table_id)
            logging.info(
                "Table is partitioned. Partition chosen to be restored: %s",
                table_metadata)

        return table_metadata

    def __get_random_partition(self, dataset_id, project_id, table_id):
        partitions = self.big_query.list_table_partitions(project_id,
                                                          dataset_id,
                                                          table_id)
        number_of_partitions = len(partitions)
        random_partition = partitions[
            random.randint(0, number_of_partitions - 1)]["partitionId"]
        table_metadata = self.big_query.get_table_or_partition(
            project_id, dataset_id, table_id, random_partition)
        return table_metadata

    @staticmethod
    def __has_been_modified_since_midnight(table_metadata):
        d = datetime.utcnow().date()
        midnight = datetime(d.year, d.month, d.day)
        return table_metadata.get_last_modified_datetime() > midnight

    @staticmethod
    def __was_modified_yesterday(table_metadata):
        d = datetime.utcnow().date()
        last_midnight = datetime(d.year, d.month, d.day)
        midnight_day_before = (last_midnight - timedelta(days=1))
        return table_metadata.get_last_modified_datetime() > midnight_day_before