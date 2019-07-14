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
    assert(vec.back() <= global_end);
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

void path_preference_summary_t::link_up(nid_t s, nid_t t, timestamp_t timestamp) {
  m_link_history_vec.at(make_index(s, t)).start(timestamp);
}

void path_preference_summary_t::link_down(nid_t s, nid_t t, timestamp_t timestamp) {
  m_link_history_vec.at(make_index(s, t)).stop(timestamp);
}

path_timestamps_t path_preference_summary_t::get_path_timestamps() const {
  path_timestamps_t result;
  for (auto& path_history : m_route_history) {
    for (auto& kv : path_history) {
      auto& path = kv.first;
      assert(1 < path.size());
      if (result.find(path) != result.end()) {
        continue;
      }
      auto timestamps = link_timestamps(path.at(0), path.at(1));
      for (std::size_t i = 1; not timestamps.empty() and i + 1 < path.size(); ++i) {
         auto next_timestamps = link_timestamps(path.at(i), path.at(i + 1));
         timestamps = intersect(timestamps, next_timestamps);
      }
      if (not timestamps.empty()) {
        result[path] = timestamps;
      }
    }
  }
  return result;
}

route_timestamps_t path_preference_summary_t::get_route_timestamps() const {
  route_timestamps_t result;
  result.resize(m_route_history.size());
  flow_id_t flow_id = 0;
  for (auto& path_history : m_route_history) {
    auto& path_timestamps = result[flow_id++];
    for (auto& kv : path_history) {
      auto& path = kv.first;
      auto& history = kv.second;
      auto ts = history.timestamps(global_stop);
      auto result = path_timestamps.emplace(path, std::move(ts));
      assert(result.second);
      assert(1 < path.size());
    }
  }
  return result;
}

path_preferences_t path_preference_summary_t::path_preferences() const {
  constexpr double zero_div_guard = 0.00001;
  path_preferences_t path_preferences;
  path_timestamps_t path_timestamps = get_path_timestamps();
  route_timestamps_t route_timestamps = get_route_timestamps();
  flow_id_t flow_id = 0;

  auto duration = [](const timestamps_t &timestamps) {
    duration_t dur = 0;
    for (std::size_t i = 0; i + 1 < timestamps.size(); i += 2) {
       assert(timestamps[i] <= timestamps[i + 1]);
       dur += timestamps[i + 1] - timestamps[i];
    }
    return dur;
  };

  for (auto& x_path_timestamps : route_timestamps) {
    for (auto& x_kv : x_path_timestamps) {
      auto& x_path = x_kv.first;
      auto& x_path_timestamps = x_kv.second;
      assert(1 < x_path.size());
      assert(!(x_path_timestamps.size() & 1));
      for (auto& y_kv : path_timestamps) {
        auto& y_path = y_kv.first;
        auto& y_link_timestamps = y_kv.second;
        assert(1 < y_path.size());
        assert(!(y_link_timestamps.size() & 1));
        if (x_path.front() != y_path.front()
            or x_path.back() != y_path.back()
            or x_path == y_path) {
          continue;
        }
        auto x_link_timestamps_iter = path_timestamps.find(x_path);
        if (x_link_timestamps_iter == path_timestamps.end()) {
          continue;
        }
        auto x_link_timestamps = x_link_timestamps_iter->second;

        auto nominator_timestamps = intersect(x_path_timestamps, y_link_timestamps);
        if (nominator_timestamps.empty()) {
          continue;
        }
        // Since path and link histories may be recorded differently (due to BMP),
        // we intersect with x_link_timestamps, because x_path_timestamps may not
        // be a subset of x_link_timestamps (again, depending on how BMP works).
        nominator_timestamps = intersect(nominator_timestamps, x_link_timestamps);
        if (nominator_timestamps.empty()) {
          continue;
        }

        auto denominator_timestamps = intersect(x_link_timestamps, y_link_timestamps);
        if (denominator_timestamps.empty()) {
          continue;
        }
        duration_t nominator_duration = duration(nominator_timestamps);
        duration_t denominator_duration = duration(denominator_timestamps);
        auto rank = nominator_duration / (denominator_duration + zero_div_guard);
        path_preferences.emplace_back(flow_id, x_path, y_path, rank);
      }
    }
    ++flow_id;
  }
  return path_preferences;
}

void find_loops(source_t start, const affected_flows_t &affected_flows,
                loops_per_flow_t &loops_per_flow) {
  ip_addr_vec_t stack, path;
  std::unordered_set<source_t> seen;
  for (auto flow : affected_flows) {
    assert(stack.empty());
    assert(seen.empty());
    assert(path.empty());

    auto &rule_ref_per_source = flow->data;
    stack.reserve(rule_ref_per_source.size() + 1);
    path.reserve(rule_ref_per_source.size() + 1);
    stack.push_back(start);
    while (not stack.empty()) {
      auto n = stack.back();
      stack.pop_back();
      auto rule_ref_per_source_iter = rule_ref_per_source.find(n);
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

void analysis_t::link_up(nid_t s, nid_t t, timestamp_t timestamp) {
  update_global_timestamps(timestamp);
  m_path_preference_summary.link_up(s, t, timestamp);
}

void analysis_t::link_down(nid_t s, nid_t t, timestamp_t timestamp) {
  update_global_timestamps(timestamp);
  m_path_preference_summary.link_down(s, t, timestamp);
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

void analysis_t::update_global_timestamps(timestamp_t timestamp) {
  if (timestamp < m_reach_summary.global_start) {
    m_reach_summary.global_start = timestamp;
  }
  if (m_reach_summary.global_stop < timestamp) {
    m_reach_summary.global_stop = timestamp;
  }
  if (m_path_preference_summary.global_stop < timestamp) {
    m_path_preference_summary.global_stop = timestamp;
  }
}

void analysis_t::update_reach_summary(timestamp_t timestamp) {
  if (m_reach_summary.spans.empty()) {
    return;
  }

  path_t path;
  ip_addr_vec_t stack;
  std::bitset<MAX_NUMBER_OF_NODES> bitset;
  stack.reserve(m_reach_summary.number_of_nodes);
  update_global_timestamps(timestamp);

  auto prepare_history_update = [timestamp](history_t& history) {
     history.start(timestamp);
     history.request_stop = false;
  };
  auto finalize_history_update = [timestamp](history_t& history) {
    // stop requests for histories that just got started are no-ops
    if (history.request_stop) {
      history.stop(timestamp);
    }
    history.request_stop = true;
  };
  for (auto flow : m_affected_flows) {
    assert(stack.empty());
    auto &history_vec = m_reach_summary.history_vec(flow->id);
    auto &rule_ref_per_source = flow->data;
    auto& path_history = m_path_preference_summary.path_history(flow);
    for (auto &kv : rule_ref_per_source) {
      assert(stack.empty());
      auto s = kv.first;
      auto base_index = m_reach_summary.number_of_nodes * s;
      stack.push_back(s);
      while (not stack.empty()) {
        auto n = stack.back();
        stack.pop_back();
        path.push_back(n);
        auto rule_ref_per_source_iter = rule_ref_per_source.find(n);
        if (rule_ref_per_source_iter == rule_ref_per_source.end()) {
          continue;
        }
        auto rule_ref = rule_ref_per_source_iter->second;
        if (rule_ref->target.size() > 1) {
          std::cerr << "Error: multicast currently unsupported\n";
          std::exit(ERROR_MULTICAST_PATH_PREFERENCE_UNSUPPORTED);
        }
        for (auto t : rule_ref->target) {
          auto index = base_index + t;
          assert(index < history_vec.size());
          if (bitset.test(t)) {
            continue;
          }
          auto &history = history_vec[index];
          prepare_history_update(history);
          bitset.set(t);
          stack.push_back(t);
        }
        if (not stack.empty()) {
          // keep only the longest path for each flow
          path_history.erase(path);
        }
      }
      assert(not path.empty());
      auto iter = path_history.lower_bound(path);
      if (iter == path_history.end() or path_history.key_comp()(path, iter->first)) {
        auto spans = spans_t({m_reach_summary.spans.back()});
        iter = path_history.emplace_hint(iter, path, history_t(spans));
      }
      prepare_history_update(iter->second);
      path.clear();
      bitset.reset();
    }
    for (auto &history : history_vec) {
      finalize_history_update(history);
    }
    for (auto &kv : path_history) {
      auto& history = kv.second;
      finalize_history_update(history);
    }
  }
}

bool analysis_t::insert_or_assign(const ip_prefix_t &ip_prefix, source_t source,
                                  const target_t &new_target,
                                  timestamp_t timestamp) {
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
