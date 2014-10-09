from __future__ import absolute_import
from twisted.internet import defer
from twisted.python import log


class RenderPool(object):
    """A pool of renders. The number of slots determines how many
    renders will be run in parallel, at the most."""

    def __init__(self, slots, network_manager, splash_proxy_factory_cls, js_profiles_path, verbosity=1):
        self.network_manager = network_manager
        self.splash_proxy_factory_cls = splash_proxy_factory_cls or (lambda profile_name: None)
        self.js_profiles_path = js_profiles_path
        self.active = set()
        self.queue = defer.DeferredQueue()
        self.verbosity = verbosity
        for n in range(slots):
            self._wait_for_render(None, n, log=False)

    def render(self, rendercls, splash_request, proxy, **kwargs):
        splash_proxy_factory = self.splash_proxy_factory_cls(proxy)
        pool_d = defer.Deferred()
        self.queue.put((rendercls, splash_request, splash_proxy_factory, kwargs, pool_d))
        self.log("queued %s" % id(splash_request))
        return pool_d

    def _wait_for_render(self, _, slot, log=True):
        if log:
            self.log("SLOT %d is available" % slot)
        d = self.queue.get()
        d.addCallback(self._start_render, slot)
        d.addBoth(self._wait_for_render, slot)
        return _

    def _start_render(self, (rendercls, splash_request, splash_proxy_factory, kwargs, pool_d), slot):
        self.log("initializing SLOT %d" % (slot, ))
        render = rendercls(
            network_manager=self.network_manager,
            splash_proxy_factory=splash_proxy_factory,
            splash_request=splash_request,
            verbosity=self.verbosity,
        )
        self.active.add(render)
        render.deferred.chainDeferred(pool_d)
        pool_d.addErrback(self._error, render, slot)
        pool_d.addBoth(self._close_render, render, slot)

        self.log("SLOT %d is creating request %s" % (slot, id(splash_request)))
        try:
            render.start(**kwargs)
        except:
            render.deferred.errback()
            raise
        self.log("SLOT %d is working on %s" % (slot, id(splash_request)))

        return render.deferred

    def _error(self, _, render, slot):
        self.log("SLOT %d finished with an error %s %s" % (slot, id(render.splash_request), render))
        return _

    def _close_render(self, _, render, slot):
        self.log("SLOT %d is closing %s %s" % (slot, id(render.splash_request), render))
        self.active.remove(render)
        render.deferred.cancel()
        render.close()
        self.log("SLOT %d done with %s %s" % (slot, id(render.splash_request), render))
        return _

    def log(self, text):
        if self.verbosity >= 2:
            log.msg(text, system='pool')
