import Utils
import BaseThreadedModule
import StatisticCollector as StatisticCollector
import Decorators
import os


@Decorators.ModuleDocstringParser
class SimpleStats(BaseThreadedModule.BaseThreadedModule):
    """
    Collect and log some simple gambolputty statistic data.

    Use this module if you just need some simple statistics on how many events are passing through gambolputty.
    Per default, statistics will just be send to stdout.

    Configuration template:

    - SimpleStats:
        interval:                      # <default: 10; type: integer; is: optional>
        event_type_statistics:         # <default: True; type: boolean; is: optional>
        receive_rate_statistics:       # <default: True; type: boolean; is: optional>
        waiting_event_statistics:      # <default: False; type: boolean; is: optional>
        emit_as_event:                 # <default: False; type: boolean; is: optional>
    """

    module_type = "misc"
    """Set module type"""

    def configure(self, configuration):
        # Call parent configure method
        BaseThreadedModule.BaseThreadedModule.configure(self, configuration)
        self.emit_as_event = self.getConfigurationValue('emit_as_event')
        self.interval = self.getConfigurationValue('interval')
        self.stats_collector = StatisticCollector.StatisticCollector()
        for counter_name in ['events_received', 'event_type_Unknown', 'event_type_httpd_access_log']:
            StatisticCollector.MultiProcessStatisticCollector().initCounter(counter_name)
        self.module_queues = {}

    def getRunTimedFunctionsFunc(self):
        @Decorators.setInterval(self.interval)
        def runTimedFunctionsFunc():
            self.accumulateEventTypeStats()
            self.accumulateReceiveRateStats()
            if self.gp.is_master:
                self.printIntervalStatistics()
        return runTimedFunctionsFunc

    def accumulateEventTypeStats(self):
        for event_type, count in self.stats_collector.getAllCounters().items():
            StatisticCollector.MultiProcessStatisticCollector().incrementCounter(event_type, count)
            self.stats_collector.resetCounter(event_type)

    def accumulateReceiveRateStats(self):
        StatisticCollector.MultiProcessStatisticCollector().incrementCounter('events_received', self.stats_collector.getCounter('events_received'))
        self.stats_collector.resetCounter('events_received')

    def printIntervalStatistics(self):
        self.logger.info("############# Statistics (PID: %s) #############" % os.getpid())
        if self.getConfigurationValue('receive_rate_statistics'):
            self.receiveRateStatistics()
        if self.getConfigurationValue('waiting_event_statistics'):
            self.eventsInQueuesStatistics()
        if self.getConfigurationValue('event_type_statistics'):
            self.eventTypeStatistics()

    def eventTypeStatistics(self):
        self.logger.info(">> EventTypes Statistics")
        for event_type, count in sorted(StatisticCollector.MultiProcessStatisticCollector().getAllCounters().items()):
            count = count.value
            if not event_type.startswith('event_type_'):
                continue
            event_name = event_type.replace('event_type_', '')
            self.logger.info("EventType: %s%s%s - Hits: %s%s%s" % (Utils.AnsiColors.YELLOW, event_name, Utils.AnsiColors.ENDC, Utils.AnsiColors.YELLOW, count, Utils.AnsiColors.ENDC))
            if self.emit_as_event:
                self.sendEvent(Utils.getDefaultEventDict({"total_count": count, "count_per_sec": (count/self.interval), "field_name": event_name, "interval": self.interval }, caller_class_name="Statistics", event_type="statistic"))
            StatisticCollector.MultiProcessStatisticCollector().resetCounter(event_type)

    def receiveRateStatistics(self):
        self.logger.info(">> Receive rate stats")
        events_received = StatisticCollector.MultiProcessStatisticCollector().getCounter('events_received')
        if not events_received:
            events_received = 0
        StatisticCollector.MultiProcessStatisticCollector().resetCounter('events_received')
        self.logger.info("Received events in %ss: %s%s (%s/eps)%s" % (self.getConfigurationValue('interval'), Utils.AnsiColors.YELLOW, events_received, (events_received/self.interval), Utils.AnsiColors.ENDC))
        if self.emit_as_event:
            self.sendEvent(Utils.getDefaultEventDict({"total_count": events_received, "count_per_sec": (events_received/self.interval), "field_name": "all_events", "interval": self.interval }, caller_class_name="Statistics", event_type="statistic"))

    def eventsInQueuesStatistics(self):
        if len(self.module_queues) == 0:
            return
        self.logger.info(">> Queue stats")
        for module_name, queue in sorted(self.module_queues.items()):
            self.logger.info("Events in %s queue: %s%s%s" % (module_name, Utils.AnsiColors.YELLOW, queue.qsize(), Utils.AnsiColors.ENDC))
            if self.emit_as_event:
                self.sendEvent(Utils.getDefaultEventDict({"queue_count": queue.qsize(),  "field_name": "queue_counts", "interval": self.interval }, caller_class_name="Statistics", event_type="statistic"))

    def initAfterFork(self):
        # Get all configured queues for waiting event stats.
        for module_name, module_info in self.gp.modules.items():
            instance = module_info['instances'][0]
            if not hasattr(instance, 'getInputQueue') or not instance.getInputQueue():
                continue
            self.module_queues[module_name] = instance.getInputQueue()
        Utils.TimedFunctionManager.startTimedFunction(self.getRunTimedFunctionsFunc())
        BaseThreadedModule.BaseThreadedModule.initAfterFork()


    def handleEvent(self, event):
        self.stats_collector.incrementCounter('events_received')
        if self.getConfigurationValue('event_type_statistics'):
            try:
                self.stats_collector.incrementCounter('event_type_%s' % event['gambolputty']['event_type'])
            except:
                pass
        yield event