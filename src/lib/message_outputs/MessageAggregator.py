import time
import BaseModule

class MessageAggregator(BaseModule.BaseModule):
    """
    This class collects a configurable amount of messages
    before it will call the handler that takes care of the
    data storage. The handlers will be run in a different
    thread pool.
    """

    data_container = []
    
    def handleData(self, data):
        self.data_container.append(data)
        if len(self.data_container) < self.config['store_data_interval']:
            return
        self.logger.debug("Sending data: %s " % self.data_container)
        self.addToOutputQueues(self.data_container)
        self.data_container = []
