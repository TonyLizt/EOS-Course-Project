(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FixedPayloadRenderer = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function createScheduler(options) {
    if (!options || typeof options.requestFrame !== 'function'
        || typeof options.prepare !== 'function'
        || typeof options.render !== 'function'
        || typeof options.isReady !== 'function'
        || typeof options.commit !== 'function') {
      throw new TypeError('fixed payload renderer requires frame, prepare, render, readiness and commit callbacks');
    }
    const stableFrames = Math.max(1, Number(options.stableFrames) || 2);
    const maxFrames = Math.max(stableFrames, Number(options.maxFrames) || 120);
    const pending = new Map();
    const order = [];
    let orderCursor = 0;
    let sequence = 0;
    let active = null;
    let scheduled = null;
    let priorityId = null;
    let lastCommitWasPriority = false;
    let destroyed = false;

    const emit = (type, job, details) => {
      if (typeof options.onEvent === 'function') {
        options.onEvent({
          type: type,
          job: job,
          details: details || null,
          activeId: active && active.id,
          pendingCount: pending.size
        });
      }
    };

    const hasNormalPending = () => {
      for (const id of pending.keys()) if (id !== priorityId) return true;
      return false;
    };

    const take = (id) => {
      const job = pending.get(id);
      if (job) pending.delete(id);
      return job || null;
    };

    const choose = () => {
      const priorityPending = priorityId && pending.has(priorityId);
      if (priorityPending && (!lastCommitWasPriority || !hasNormalPending())) {
        return take(priorityId);
      }
      if (order.length) {
        for (let checked = 0; checked < order.length; checked += 1) {
          const index = (orderCursor + checked) % order.length;
          const id = order[index];
          if (id !== priorityId && pending.has(id)) {
            orderCursor = (index + 1) % order.length;
            return take(id);
          }
        }
      }
      return priorityPending ? take(priorityId) : null;
    };

    const ensureFrame = () => {
      if (destroyed || scheduled != null || (!active && !pending.size)) return;
      scheduled = options.requestFrame(step);
    };

    const finish = (type, details) => {
      const completed = active;
      if (type === 'commit') lastCommitWasPriority = completed.id === priorityId;
      emit(type, completed, details);
      active = null;
      ensureFrame();
    };

    function step(timestamp) {
      scheduled = null;
      if (destroyed) return;
      if (!active) {
        active = choose();
        if (!active) return;
        active.attempts = 0;
        active.readyStreak = 0;
        active.startedAt = timestamp;
        try {
          options.prepare(active);
          emit('begin', active);
        } catch (error) {
          if (typeof options.onError === 'function') options.onError(error, active);
          finish('error', { error: String(error && error.stack || error) });
          return;
        }
      }
      active.attempts += 1;
      let readiness;
      try {
        options.render(active);
        readiness = options.isReady(active);
        const ready = typeof readiness === 'object' ? readiness.ready : readiness;
        active.readyStreak = ready ? active.readyStreak + 1 : 0;
        emit('render', active, typeof readiness === 'object' ? readiness : { ready: Boolean(ready) });
        if (active.readyStreak >= stableFrames) {
          options.commit(active);
          finish('commit', { attempts: active.attempts, readyStreak: active.readyStreak });
          return;
        }
        if (active.attempts >= maxFrames) {
          finish('drop', { attempts: active.attempts, reason: 'renderer did not reach a stable complete frame' });
          return;
        }
      } catch (error) {
        if (typeof options.onError === 'function') options.onError(error, active);
        finish('error', { error: String(error && error.stack || error) });
        return;
      }
      ensureFrame();
    }

    return {
      request(id, payload) {
        if (destroyed || !id) return null;
        if (!order.includes(id)) order.push(id);
        const job = { id: id, payload: payload, sequence: ++sequence };
        pending.set(id, job); // Coalesce only queued work; never replace the active frame.
        ensureFrame();
        return job.sequence;
      },
      setPriority(id) {
        priorityId = id || null;
        ensureFrame();
      },
      getState() {
        return {
          activeId: active && active.id,
          activeSequence: active && active.sequence,
          pendingIds: Array.from(pending.keys()),
          priorityId: priorityId,
          destroyed: destroyed
        };
      },
      destroy() {
        destroyed = true;
        pending.clear();
        active = null;
        if (scheduled != null && typeof options.cancelFrame === 'function') {
          options.cancelFrame(scheduled);
        }
        scheduled = null;
      }
    };
  }

  return { createScheduler: createScheduler };
}));
