// Copyright 2018 Alex Horn. All rights reserved.
// Use of this source code is governed by a LICENSE.

#include "analysis.hh"
#include <bitset>
#include <cstdlib>
#include <iostream>

namespace nopticon {

void history_t::refresh(timestamp_t timestamp) noexcept {
  // If we're in 'stop', then set tail to new start;
  // otherwise, cause tail to catch up with head.
  bool is_stop = m_head & 1;
  auto h = is_stop ? index(m_head + 1) : m_head;
  for (auto& slice : m_slices) {
    slice.duration = 0;
    slice.tail = h;
    assert(!(h & 1));
  }
  if (not is_stop) {
    m_time_window[h] = timestamp;
  }
}

rank_t history_t::rank(const slice_t &slice, timestamp_t global_start,
                       timestamp_t global_stop) const noexcept {
  constexpr double boost = 0.00001;
  auto duration = static_cast<double>(slice.duration);
  assert(global_start <= global_stop);
  // Timestamps of non-empty histories are non-decreasing.
  assert(duration == 0 or oldest_start_time(slice) <= newest_time());
  if (!(m_head & 1) and newest_time() <= global_stop) {
    // We're in 'start' and need to add a missing 'stop'.
    duration += global_stop - newest_time() + boost;
  }
  // The duration of a slice exceeds its span in two scenarios:
  // 1. Slice is open and we close it with a large global_stop time;
  // 2. Slice has only one start/stop pair whose difference is larger
  //    than the span of the slice
  // In both casese, we ensure that the rank of the slice is 1.
  assert(duration <= (global_stop - global_start) + boost);
  double span = duration > slice.span() ? duration :
    std::min(slice.span(), global_stop - global_start);
  return duration / (span + boost);
}

void history_t::update_duration(bool is_stop, timestamp_t current) {
  assert(current != 0);
  // Start: 0, 2, 4, ...
  // Stop: 1, 3, 5, ...
  auto newest = m_time_window.at(m_head);
  if ((m_head & 1) == is_stop) {
    // - We're currently in 'start' or 'stop' and got
    //   another start or stop request, respectively;
    // - Stop requests for which there is no start.
    return;
  }
  // currently in 'start' but need to be in 'stop', or vice versa
  if (newest >= current) {
    // ignore simultaneous and out-of-order arrivals
    return;
  }
  m_time_window.at(m_head = index(m_head + 1)) = current;
  if (is_stop) {
    assert(m_head & 1);
    auto next_head = index(m_head + 1);
    for (auto &slice : m_slices) {
      auto &d = slice.duration;
      auto &tail = slice.tail;
      assert(!(tail & 1));
      d += current - newest;
      auto actual_span = slice.span();
      for (;;) {
        assert(!(tail & 1));
        auto oldest_start = oldest_start_time(slice);
        assert(oldest_start != 0);
        assert(oldest_start <= newest);
        actual_span = current - oldest_start;
        if (tail == next_head) {
          next_head = m_time_window.size();
          assert(m_head + 1 == next_head);
          m_time_window.resize(m_time_window.size() << 1);

          // unprovable, but something we'd like
          assert(m_time_window.size() <= (1 << 10));
        }
        if (actual_span <= slice.span() or tail + 1 == m_head) {
          break;
        }
        auto oldest_stop = m_time_window.at(index(tail + 1));
        assert(oldest_start <= oldest_stop);
        tail = index(tail + 2);
        d -= oldest_stop - oldest_start;
      }
      assert(tail + 1 == m_head or actual_span <= slice.span());
    }
  }
}

void history_t::start(timestamp_t current) { update_duration(false, current); }
void history_t::stop(timestamp_t current) { update_duration(true, current); }

timestamps_t history_t::timestamps(timestamp_t global_end) const noexcept {
  duration_t duration = 0;
  auto tail = m_time_window.size();
  for (auto& slice : m_slices) {
    if (slice.duration >= duration) {
      tail = slice.tail;
    }
  }
  if (tail >= m_time_window.size() or ((m_head & 1) and index(m_head + 1) == tail)) {
    return {};
  }
  auto i = tail;
  timestamps_t vec;
  vec.reserve(m_time_window.size());
  for (;;) {
    vec.push_back(m_time_window[i]);
    i = index(i + 1);
    if (vec.back() > m_time_window[i] or i == tail) {
      break;
    }
  }
  if (vec.size() & 1) {
    vec.push_back(global_end);
  }
  return vec;
}

void history_t::reset() noexcept {
  m_head = m_time_window.size() - 1;
  for (auto &slice : m_slices) {
    slice.duration = 0;
    slice.tail = 0;
  }
}

reach_summary_t::reach_summary_t(std::size_t number_of_nodes)
    : spans{}, number_of_nodes{number_of_nodes} {
  assert(number_of_nodes <= analysis_t::MAX_NUMBER_OF_NODES);
}

reach_summary_t::reach_summary_t(const spans_t &spans,
                                     std::size_t number_of_nodes)
    : spans{spans}, number_of_nodes{number_of_nodes} {
  assert(number_of_nodes <= analysis_t::MAX_NUMBER_OF_NODES);
}

void reach_summary_t::reset() noexcept {
  for (auto &history_vec : m_tensor) {
    for (auto &history : history_vec) {
      history.reset();
    }
  }
}

void reach_summary_t::refresh(timestamp_t timestamp) noexcept {
  if (global_start < timestamp) {
    global_start = timestamp;
  }
  if (global_stop < timestamp) {
    global_stop = timestamp;
  }
  assert(global_start <= global_stop);
  for (auto &history_vec : m_tensor) {
    for (auto &history : history_vec) {
      history.refresh(timestamp);
    }
  }
}

ranks_t reach_summary_t::ranks(const history_t &history) const {
  ranks_t ranks;
  ranks.reserve(history.slices().size());
  for (auto &slice : history.slices()) {
    ranks.push_back(history.rank(slice, global_start, global_stop));
  }
  return ranks;
}

const slices_t &reach_summary_t::slices(flow_id_t flow_id, nid_t s,
                                          nid_t t) const {
  static slices_t s_empty_slices;
  if (flow_id >= m_tensor.size()) {
    return s_empty_slices;
  }
  auto &history_vec = m_tensor[flow_id];
  auto index = make_index(s, t);
  if (index >= history_vec.size()) {
    return s_empty_slices;
  }
  return history_vec[index].slices();
}

history_vec_t &reach_summary_t::history_vec(flow_id_t flow_id) {
  if (flow_id >= m_tensor.size()) {
    auto old_size = m_tensor.size();
    m_tensor.resize((flow_id + 1) << 1);
    for (std::size_t i = old_size; i < m_tensor.size(); ++i) {
      assert(m_tensor[i].empty());
      history_t history{spans};
      m_tensor[i].resize(number_of_nodes * number_of_nodes, history);
    }
  }
  assert(flow_id < m_tensor.size());
  return m_tensor[flow_id];
}

const history_t &reach_summary_t::history(flow_id_t flow_id, nid_t s,
                                            nid_t t) const {
  static history_t s_empty_history{spans_t{}};
  if (flow_id >= m_tensor.size()) {
    return s_empty_history;
  }
  auto &history_vec = m_tensor[flow_id];
  auto index = make_index(s, t);
  if (index >= history_vec.size()) {
    return s_empty_history;
  }
  return history_vec[index];
}

history_t &reach_summary_t::history(flow_id_t flow_id, nid_t s, nid_t t) {
  auto &hv = history_vec(flow_id);
  auto index = make_index(s, t);
  assert(index < hv.size());
  return hv[index];
}

bandwidth_summary_t::bandwidth_summary_t(std::size_t number_of_nodes)
    : number_of_nodes{number_of_nodes} {
  assert(number_of_nodes <= analysis_t::MAX_NUMBER_OF_NODES);
}

void bandwidth_summary_t::reset() noexcept {
  m_minimum.assign(m_minimum.size(), -1);
}

void analysis_t::update_bandwidth_summary(source_t start,
        const affected_flows_t &affected_flows) {
  // TODO
}

void find_loops(source_t start, const affected_flows_t &affected_flows,
                loops_per_flow_t &loops_per_flow) {
  ip_addr_vec_t stack, path;
  std::unordered_set<source_t> seen;
  // Check for a forwarding loop for each PEC affected by a rule change
  for (auto flow : affected_flows) {
    assert(stack.empty());
    assert(seen.empty());
    assert(path.empty());

    auto &rule_ref_per_source = flow->data;
    stack.reserve(rule_ref_per_source.size() + 1);
    path.reserve(rule_ref_per_source.size() + 1);
    // Start searching from the node on which a rule was changed
    stack.push_back(start);
    while (not stack.empty()) {
      auto n = stack.back();
      stack.pop_back();
      // Get next hop for for PEC from router n
      auto rule_ref_per_source_iter = rule_ref_per_source.find(n);
      // Check if we have reached a dead-end (i.e., no next hop)
      if (rule_ref_per_source_iter == rule_ref_per_source.end()) {
        if (path.empty()) {
          assert(stack.empty());
          break;
        }
        path.pop_back();
        continue;
      }
      auto rule_ref = rule_ref_per_source_iter->second;
      auto insert_result = seen.insert(n);
      // Check if node was already seen
      if (not nopticon::ok(insert_result)) {
        assert(not path.empty());
        auto min_iter = std::min_element(path.begin(), path.end());
        std::rotate(path.begin(), min_iter, path.end());
        loops_per_flow[flow].push_back(std::move(path));
        path = ip_addr_vec_t();
        stack.clear();
        break;
      }
      path.push_back(n);
      stack.insert(stack.end(), rule_ref->target.begin(),
                   rule_ref->target.end());
    }
    seen.clear();
    path.clear();
  }
}

static bool is_connected(const rule_ref_per_source_t &rule_ref_per_source,
                         nid_t source, nid_t target) {
  auto rule_ref_per_source_iter = rule_ref_per_source.find(source);
  if (rule_ref_per_source_iter == rule_ref_per_source.end()) {
    return false;
  }
  auto rule_ref = rule_ref_per_source_iter->second;
  auto target_iter =
      std::find(rule_ref->target.begin(), rule_ref->target.end(), target);
  return target_iter != rule_ref->target.end();
}

bool check_loop(const_flow_t flow, const loop_t &loop) {
  auto &rule_ref_per_source = flow->data;
  auto loop_iter = loop.begin();
  assert(loop_iter != loop.end());
  for (; std::next(loop_iter) != loop.end(); ++loop_iter) {
    if (not is_connected(rule_ref_per_source, *loop_iter,
                         *std::next(loop_iter))) {
      return false;
    }
  }
  return is_connected(rule_ref_per_source, loop.back(), loop.front());
}

void analysis_t::clean_up() {
  for (auto flow : m_affected_flows) {
    auto loops_per_flow_iter = m_loops_per_flow.find(flow);
    if (loops_per_flow_iter == m_loops_per_flow.end()) {
      continue;
    }
    loops_t loops;
    for (auto &loop : loops_per_flow_iter->second) {
      if (check_loop(flow, loop)) {
        loops.push_back(std::move(loop));
      }
    }
    if (loops.empty()) {
      m_loops_per_flow.erase(flow);
    } else {
      m_loops_per_flow[flow] = std::move(loops);
    }
  }
}

void analysis_t::update_reach_summary(timestamp_t timestamp) {
  ip_addr_vec_t stack;
  std::bitset<MAX_NUMBER_OF_NODES> bitset;
  stack.reserve(m_reach_summary.number_of_nodes);

  if (timestamp < m_reach_summary.global_start) {
    m_reach_summary.global_start = timestamp;
  }
  if (m_reach_summary.global_stop < timestamp) {
    m_reach_summary.global_stop = timestamp;
  }

  for (auto flow : m_affected_flows) {
    assert(stack.empty());
    auto &history_vec = m_reach_summary.history_vec(flow->id);
    auto &rule_ref_per_source = flow->data;
    for (auto &kv : rule_ref_per_source) {
      assert(stack.empty());
      auto start = kv.first;
      auto base_index = m_reach_summary.number_of_nodes * start;
      stack.push_back(start);
      while (not stack.empty()) {
        auto n = stack.back();
        stack.pop_back();
        auto rule_ref_per_source_iter = rule_ref_per_source.find(n);
        if (rule_ref_per_source_iter == rule_ref_per_source.end()) {
          continue;
        }
        auto rule_ref = rule_ref_per_source_iter->second;
        for (auto t : rule_ref->target) {
          auto index = base_index + t;
          assert(index < history_vec.size());
          if (bitset.test(t)) {
            continue;
          }
          auto &history = history_vec[index];
          history.start(timestamp);
          history.request_stop = false;
          bitset.set(t);
          history.can_be_direct |= bitset.count() == 1;
          stack.push_back(t);
        }
      }
      bitset.reset();
      assert(bitset.count() == 0);
    }
    for (auto &history : history_vec) {
      // stop requests for histories that just got started are no-ops
      if (history.request_stop) {
        history.stop(timestamp);
      }
      history.request_stop = true;
    }
  }
}

bool analysis_t::insert_or_assign(const ip_prefix_t &ip_prefix, source_t source,
                                  const target_t &new_target,
                                  timestamp_t timestamp,
                                  bandwidth_t bandwidth) {
  m_affected_flows.clear();
  bool status = m_flow_graph.insert_or_assign(ip_prefix, source, new_target,
                                              m_affected_flows);
  clean_up();
  find_loops(source, m_affected_flows, m_loops_per_flow);
  if (timestamp != 0) {
    update_reach_summary(timestamp);
  }
  return status;
}

bool analysis_t::erase(const ip_prefix_t &ip_prefix, source_t source,
                       timestamp_t timestamp) {
  m_affected_flows.clear();
  bool status = m_flow_graph.erase(ip_prefix, source, m_affected_flows);
  clean_up();
  find_loops(source, m_affected_flows, m_loops_per_flow);
  if (timestamp != 0) {
    update_reach_summary(timestamp);
  }
  return status;
}

timestamps_t intersect(const timestamps_t &a, const timestamps_t &b) {
  if (a.empty() or b.empty()) {
    return {};
  }
  assert(std::is_sorted(a.begin(), a.end()));
  assert(std::is_sorted(b.begin(), b.end()));
  assert(!(a.size() & 1));
  assert(!(b.size() & 1));
  timestamps_t c;
  c.reserve(std::max(a.size(), b.size()));

  constexpr bool A = 0, B = 1;
  timestamps_t::size_type more_array[] = {a.size(), b.size()};
  timestamps_t::const_iterator iter_array[] = {a.cbegin(), b.cbegin()};
  timestamps_t::const_iterator end_array[] = {a.cend(), b.cend()};
  timestamp_t low[] = {a[0], b[0]}, high[] = {0, 0};

  auto fast_forward = [&](bool X) {
    const auto Y = !X;
    auto x_end = end_array[X];
    auto x_iter = std::lower_bound(iter_array[X], x_end, low[Y]);
    if (x_iter == x_end) {
      return true;
    }
    auto x_distance = std::distance(iter_array[X], x_iter);
    if (x_distance & 1) {
      --x_iter;
      --x_distance;
    }
    iter_array[X] = x_iter;
    more_array[X] -= x_distance;
    assert(2 <= more_array[X]);
    return false;
  };
  auto advance = [&](bool X) {
    auto& _iter = iter_array[X];
    auto& _more = more_array[X];
    auto& _low = low[X];
    auto& _high = high[X];
    assert(2 <= _more);
    _more -= 2;
    _low = *(_iter++);
    _high = *(_iter++);
    assert(_low != 0);
    assert(_high != 0);
    assert(_low <= _high);
  };
  auto process_both_intervals = [&]() {
    if (low[A] <= high[B] and low[B] <= high[A]) {
      auto _low = std::max(low[A], low[B]);
      auto _high = std::min(high[A], high[B]);
      if (not c.empty() and c.back() == _low) {
        c.back() = _high;
      } else {
        c.push_back(_low);
        c.push_back(_high);
      }
      return false;
    }
    return true;
  };
  while (more_array[A] and more_array[B]) {
    if (high[A] < high[B]) {
      if (fast_forward(A)) {
        return c;
      }
      advance(A);
    } else {
      if (fast_forward(B)) {
        return c;
      }
      advance(B);
    }
    process_both_intervals();
  }
  bool X = more_array[B], Y = !X;
  assert(more_array[Y] == 0);
  if (more_array[X]) {
    fast_forward(X);
    do {
      advance(X);
      if (process_both_intervals()) {
        break;
      }
    } while (more_array[X]);
  }
  return c;
}

} // namespace nopticon
