#!/usr/bin/python
# -*- coding: UTF-8 -*-
import Utils
import multiprocessing
import ConfigurationValidator
import StatisticCollector as StatisticCollector
import sys
import os
import signal
import time
import getopt
import logging.config
import threading
import Queue
import yaml

module_dirs = ['input',
               'parser',
               'modifier',
               'misc',
               'output',
               'webserver',
               'cluster']

# Expand the include path to our libs and modules.
# TODO: Check for problems with similar named modules in 
# different module directories.
pathname = os.path.abspath(__file__)
pathname = pathname[:pathname.rfind("/")]
[sys.path.append(pathname + "/" + mod_dir) for mod_dir in module_dirs]

class Node:
    def __init__(self, module):
        self.children = []
        self.module = module

    def addChild(self, node):
        self.children.append(node)


def hasLoop(node, stack=[]):
    if not stack:
        stack.append(node)
    for current_node in node.children:
        if current_node in stack:
            return [current_node]
        stack.append(current_node)
        return hasLoop(current_node, stack)
    return []

class GambolPutty:
    """A stream parser with configurable modules and message paths.
    
    GambolPutty helps to parse text based streams by providing a framework of modules.
    These modules can be combined via a simple configuration in any way you like. Have
    a look at the example config gambolputty.conf.example in the conf folder.
    
    This is the main class that reads the configuration, includes the needed modules
    and connects them via queues as configured.
    """

    def __init__(self, path_to_config_file=False):
        self.alive = True
        self.main_process_pid = os.getpid()
        self.modules = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        if path_to_config_file:
            self.readConfiguration(path_to_config_file)

    def produceQueue(self, module_instance, queue_max_size=20):
        """Returns a queue with queue_max_size"""
        if isinstance(module_instance, threading.Thread):
            return Queue.Queue(queue_max_size)
        if isinstance(module_instance, multiprocessing.Process):
            queue = multiprocessing.Queue(queue_max_size)
            queue = Utils.BufferedQueue(queue)
            return queue

    def readConfiguration(self, path_to_config_file):
        """Loads and parses the configuration

        :param path_to_config_file: path to the configuration file
        :type path_to_config_file: str
        """
        try:
            conf_file = open(path_to_config_file)
            self.configuration = yaml.load(conf_file)
        except:
            etype, evalue, etb = sys.exc_info()
            self.logger.error("%sCould not read config file %s. Exception: %s, Error: %s.%s" % (
            Utils.AnsiColors.WARNING, path_to_config_file, etype, evalue, Utils.AnsiColors.ENDC))
            sys.exit(255)

    def getConfiguration(self):
        return self.configuration

    def setConfiguration(self, configuration, merge=True):
        if type(configuration) is not list:
            return
        if merge:
            # If merge is true keep currently configured modules and only merge new ones.
            for module_info in configuration:
                if module_info not in self.configuration:
                    self.configuration.append(module_info)
        else:
            self.configuration = configuration

    def configure(self):
        gp_conf = {}
        for idx, configuration in enumerate(self.configuration):
            if 'GambolPutty' in configuration:
                gp_conf = configuration
                break
        self.default_pool_size = configuration['default_pool_size'] if 'default_pool_size' in gp_conf else multiprocessing.cpu_count() - 1
        self.default_queue_size = configuration['default_queue_size'] if 'default_queue_size' in gp_conf else 20
        self.default_mp_queue_buffer_size = configuration['default_queue_buffer_size'] if 'default_queue_buffer_size' in gp_conf else 100

    def runModules(self):
        """
        Start the configured modules
        """
        # All modules are completely configured, call modules run method if it exists.
        for module_name, module_info in sorted(self.modules.items(), key=lambda x: x[1]['idx']):
            if len(module_info['instances']) > 1:
                self.logger.info("%sUsing module %s, pool size: %s%s." % (Utils.AnsiColors.LIGHTBLUE, module_name, len(module_info['instances']), Utils.AnsiColors.ENDC))
            else:
                self.logger.info("%sUsing module %s%s." % (Utils.AnsiColors.LIGHTBLUE, module_name, Utils.AnsiColors.ENDC))
            for instance in module_info['instances']:
                name = module_info['alias'] if 'alias' in module_info else module_name
                try:
                    if isinstance(instance, threading.Thread) or isinstance(instance, multiprocessing.Process):
                        # The default 'start' method of threading.Thread will call the 'run' method of the module.
                        instance.start()
                    elif getattr(instance, "run", None):
                        # Call 'run' method directly.
                        instance.run()
                except:
                    etype, evalue, etb = sys.exc_info()
                    self.logger.warning("%sError calling run/start method of %s. Exception: %s, Error: %s.%s" % (Utils.AnsiColors.WARNING, name, etype, evalue, Utils.AnsiColors.ENDC))
        import tornado.ioloop
        tornado.ioloop.IOLoop.instance().start()

    def initModule(self, module_name):
        """ Initalize a module.

        :param module_name: module to initialize
        :type module_name: string
        """
        self.logger.debug("Initializing module %s." % (module_name))
        try:
            module = __import__(module_name)
            module_class = getattr(module, module_name)
            instance = module_class(self, StatisticCollector.StatisticCollector())
        except:
            etype, evalue, etb = sys.exc_info()
            self.logger.error("%sCould not init module %s. Exception: %s, Error: %s.%s" % (
            Utils.AnsiColors.WARNING, module_name, etype, evalue, Utils.AnsiColors.ENDC))
            sys.exit(255)
        return instance

    def initModulesFromConfig(self):
        """ Initalize all modules from the current config.
        
            The pool size defines how many threads for this module will be started.
        """
        # Init modules as defined in config
        for idx, module_info in enumerate(self.configuration):
            # Only consider module configurations.
            if 'module' not in module_info:
                continue
            pool_size = module_info['pool_size'] if "pool_size" in module_info else self.default_pool_size
            module_instances = []
            module_name = False
            for _ in range(pool_size):
                # Build first instance.
                module_instance = self.initModule(module_info['module'])
                # Set module name. Use alias if it was set in configuration.
                module_name = module_info['module'] if 'alias' not in module_info else module_info['alias']
                # Append to internal list.
                module_instances.append(module_instance)
                # If instance is not configured to run in parallel, only create one instance, no matter what the pool_size configuration says.
                if not module_instance.can_run_parallel:
                    break
            if module_name:
                self.modules[module_name] = {'idx': idx,
                                             'instances': module_instances,
                                             'type': module_instance.module_type,
                                             'queue_size': module_info[ 'queue_size'] if 'queue_size' in module_info else self.default_queue_size,
                                             'configuration': module_info,
                                             'receivers': module_info['receivers'] if 'receivers' in module_info else None}

    def configureModules(self):
        # Call configuration of module
        configurationValidator = ConfigurationValidator.ConfigurationValidator()
        for module_name, module_info in sorted(self.modules.items(), key=lambda x: x[1]['idx']):
            configuration = module_info['configuration'] if 'configuration' in module_info else {}
            passed_config_test = False
            for module_instance in module_info['instances']:
                try:
                    module_instance.configure(module_info['configuration'])
                    if not passed_config_test:
                        configuration_errors = configurationValidator.validateModuleInstance(module_instance)
                    if configuration_errors:
                        self.logger.error("%sCould not configure module %s. Problems: %s.%s" % (Utils.AnsiColors.FAIL, module_name, configuration_errors, Utils.AnsiColors.ENDC))
                        self.shutDown()
                    passed_config_test = True
                except:
                    etype, evalue, etb = sys.exc_info()
                    self.logger.error("%sCould not configure module %s. Exception: %s, Error: %s.%s" % (Utils.AnsiColors.FAIL, module_name, etype, evalue, Utils.AnsiColors.ENDC))
                    self.shutDown()

    def initEventStream(self):
        """ Connect modules.
        
        The configuration allows to connect the modules via the <receivers> parameter.
        This method creates the queues and connects the modules via this queues.
        To prevent loops a sanity check is performed before all modules are connected.
        """
        # All modules are initialized, connect producer and consumers via a queue.
        queues = {}
        module_loop_buffer = []
        for module_name, module_info in self.modules.iteritems():
            # Iterate over all instances
            for instance in module_info['instances']:
                if "receivers" not in module_info or module_info['receivers'] is None:
                    continue
                for receiver_data in module_info["receivers"]:
                    receiver_filter_config = {}
                    if isinstance(receiver_data, dict):
                        receiver_name, receiver_filter_config = receiver_data.iteritems().next()
                    else:
                        receiver_name = receiver_data
                    self.logger.debug("%s will send its output to %s." % (module_name, receiver_name))
                    if receiver_name not in self.modules:
                        self.logger.warning( "%sCould not add %s as receiver for %s. Module not found.%s" % ( Utils.AnsiColors.WARNING, receiver_name, module_name, Utils.AnsiColors.ENDC))
                        continue
                    for receiver_instance in self.modules[receiver_name]['instances']:
                        # If the receiver is a thread or a process, produce the needed queue.
                        if isinstance(receiver_instance, threading.Thread) or isinstance(receiver_instance, multiprocessing.Process):
                            if receiver_name not in queues:
                                queues[receiver_name] = self.produceQueue(receiver_instance, self.modules[receiver_name]['queue_size'])
                            try:
                                if not receiver_instance.getInputQueue():
                                    receiver_instance.setInputQueue(queues[receiver_name])
                            except AttributeError:
                                self.logger.error("%s%s can not be set as receiver. It seems to be incompatible." % (Utils.AnsiColors.WARNING, receiver_name, Utils.AnsiColors.ENDC))
                        # Build a node structure used for the loop test.
                        try:
                            node = (node for node in module_loop_buffer if node.module == instance).next()
                        except:
                            node = Node(instance)
                            module_loop_buffer.append(node)
                        try:
                            receiver_node = (node for node in module_loop_buffer if \
                                             node.module == receiver_instance).next()
                        except:
                            receiver_node = Node(receiver_instance)
                            module_loop_buffer.append(receiver_node)
                        node.addChild(receiver_node)
                    # Add a single instance as receiver to module. If the receiver is a thread or multiprocess, they share the same queue.
                    if isinstance(receiver_instance, threading.Thread) or isinstance(receiver_instance, multiprocessing.Process):
                        instance.addReceiver(receiver_name, queues[receiver_name])
                    else:
                        instance.addReceiver(receiver_name, receiver_instance)
                    # Set filter if configured.
                    if 'filter' in receiver_filter_config:
                        receiver_filter = Utils.compileStringToConditionalObject("matched = %s" % receiver_filter_config['filter'], 'event.get("%s", False)')
                        instance.setFilter(receiver_name, receiver_filter)
        # Check if the configuration produces a loop.
        # This code can definitely be made more efficient...  
        for node in module_loop_buffer:
            for loop in hasLoop(node, stack=[]):
                self.logger.error(
                    "%sChaining of modules produced a loop. Check configuration. Module: %s.%s" % (
                    Utils.AnsiColors.FAIL, loop.module.__class__.__name__, Utils.AnsiColors.ENDC))
                self.shutDown()

    def getModuleByName(self, module_name, silent=True):
        try:
            return self.modules[module_name]
        except KeyError:
            if not silent:
                self.logger.error("%sGet module by name %s failed. No such module.%s" % (Utils.AnsiColors.FAIL, module_name, Utils.AnsiColors.ENDC))
            return None

    def run(self):
        # Catch Keyboard interrupt here. Catching the signal seems
        # to be more reliable then using try/except when running
        # multiple processes under pypy.
        signal.signal(signal.SIGINT, self.shutDown)
        signal.signal(signal.SIGALRM, self.restart)
        self.runModules()
        while self.alive:
            time.sleep(.5)

    def restart(self, signum=False, frame=False):
        self.logger.info("%sRestarting GambolPutty.%s" % (Utils.AnsiColors.LIGHTBLUE, Utils.AnsiColors.ENDC))
        self.shutDownModules()
        self.configure()
        self.initModulesFromConfig()
        self.configureModules()
        self.initEventStream()
        self.runModules()

    def shutDown(self, signum=False, frame=False):
        # If a module started a subprocess, this will get called for all subprocesses started.
        # Still we know the pid of the main process. So only log if we are in the finaly shutdown stage.
        silent = self.main_process_pid != os.getpid()
        if not silent:
            self.logger.info("%sShutting down GambolPutty.%s" % (Utils.AnsiColors.LIGHTBLUE, Utils.AnsiColors.ENDC))
        self.alive = False
        self.shutDownModules(silent)
        if not silent:
            self.logger.info("%sShutdown complete.%s" % (Utils.AnsiColors.LIGHTBLUE, Utils.AnsiColors.ENDC))
        sys.exit(0)

    def shutDownModules(self, silent=False):
        # Shutdown all input modules.
        for module_name, module_info in self.modules.iteritems():
            for instance in module_info['instances']:
                if instance.module_type == "input":
                    instance.shutDown(silent)
        # Give remaining queued events some time.
        time.sleep(.5)
        # Shutdown all other modules.
        for module_name, module_info in self.modules.iteritems():
            for instance in module_info['instances']:
                if instance.module_type != "input":
                    instance.shutDown(silent)

def usage():
    print 'Usage: ' + sys.argv[0] + ' -c <path/to/config.conf>'

if "__main__" == __name__:
    config_pathname = os.path.abspath(sys.argv[0])
    config_pathname = config_pathname[:config_pathname.rfind("/")] + "/../conf"
    logging.config.fileConfig('%s/logger.conf' % config_pathname)
    path_to_config_file = ""
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hc:", ["help", "conf="])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        elif opt in ("-c", "--conf"):
            path_to_config_file = arg
    if not path_to_config_file:
        usage()
        sys.exit(2)
    gp = GambolPutty(path_to_config_file)
    gp.configure()
    gp.initModulesFromConfig()
    gp.configureModules()
    gp.initEventStream()
    gp.run()