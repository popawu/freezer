# (c) Copyright 2014,2015 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# PyCharm will not recognize queue. Puts red squiggle line under it. That's OK.
from six.moves import queue

from oslo_config import cfg
from oslo_log import log

from freezer.storage import base
from freezer.storage.exceptions import StorageException
from freezer.utils import streaming

CONF = cfg.CONF
logging = log.getLogger(__name__)


class MultipleStorage(base.Storage):

    def remove_backup(self, backup):
        raise Exception()

    def backup_blocks(self, backup):
        raise Exception()

    def info(self):
        for s in self.storages:
            s.info()

    def write_backup(self, rich_queue, backup):
        output_queues = [streaming.RichQueue() for x in self.storages]
        except_queues = [queue.Queue() for x in self.storages]
        threads = ([streaming.QueuedThread(storage.write_backup, output_queue,
                    except_queue, kwargs={"backup": backup}) for
                    storage, output_queue, except_queue in
                    zip(self.storages, output_queues, except_queues)])

        for thread in threads:
            thread.daemon = True
            thread.start()

        StorageManager(rich_queue, output_queues).transmit()

        for thread in threads:
            thread.join()

        def handle_exception_queue(except_queue):
            if not except_queue.empty:
                while not except_queue.empty():
                    e = except_queue.get_nowait()
                    logging.critical('Storage error: {0}'.format(e))
                return True
            else:
                return False

        got_exception = None
        for except_queue in except_queues:
            got_exception = (handle_exception_queue(except_queue) or
                             got_exception)

        if (got_exception):
            raise StorageException("Storage error. Failed to backup.")

    def find_all(self, hostname_backup_name):
        backups = [b.find_all(hostname_backup_name) for b in self.storages]
        # flat the list
        return [item for sublist in backups for item in sublist]

    def prepare(self):
        pass

    def upload_meta_file(self, backup, meta_file):
        for storage in self.storages:
            storage.upload_meta_file(backup, meta_file)

    def __init__(self, work_dir, storages):
        """
        :param storages:
        :type storages: list[freezer.storage.base.Storage]
        :return:
        """
        super(MultipleStorage, self).__init__(work_dir)
        self.storages = storages

    def download_freezer_meta_data(self, backup):
        # TODO(DEKLAN): Need to implement.
        pass

    def get_file(self, from_path, to_path):
        # TODO(DEKLAN): Need to implement.
        pass

    def meta_file_abs_path(self, backup):
        # TODO(DEKLAN): Need to implement.
        pass

    def upload_freezer_meta_data(self, backup, meta_dict):
        # TODO(DEKLAN): Need to implement.
        pass


class StorageManager(object):

    def __init__(self, input_queue, output_queues):
        """
        :type input_queue: streaming.RichQueue
        :param input_queue:
        :type output_queues: collections.Iterable[streaming.RichQueue]
        :param output_queues:
        :return:
        """
        self.input_queue = input_queue
        self.output_queues = output_queues
        self.broken_output_queues = set()

    def send_message(self, message, finish=False):
        for output_queue in self.output_queues:
            if output_queue not in self.broken_output_queues:
                try:
                    if finish:
                        output_queue.finish()
                    else:
                        output_queue.put(message)
                except Exception as e:
                    logging.exception(e)
                    StorageManager.one_fails_all_fail(
                        self.input_queue, self.output_queues)
                    self.broken_output_queues.add(output_queue)

    def transmit(self):
        for message in self.input_queue.get_messages():
            self.send_message(message)
        self.send_message("", True)

    @staticmethod
    def one_fails_all_fail(input_queue, output_queues):
        input_queue.force_stop()
        for output_queue in output_queues:
            output_queue.force_stop()
        raise Exception("All fail")
