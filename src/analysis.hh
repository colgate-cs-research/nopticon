// Copyright 2018 Alex Horn. All rights reserved.
// Use of this source code is governed by a LICENSE.

#pragma once

#include "flow_graph.hh"

namespace nopticon {

typedef std::vector<nid_t> loop_t;
typedef std::vector<loop_t> loops_t;
typedef std::unordered_map<const_flow_t, loops_t> loops_per_flow_t;

void find_loops(source_t, const affected_flows_t &, loops_per_flow_t &);

bool check_loop(const_flow_t, const loop_t &);

/// Microseconds
typedef uint64_t duration_t;
typedef uint64_t timestamp_t;

class slice_t {
public:
  slice_t(duration_t span) : m_span{span} {}

  /// total slice-time in which a property held
  duration_t duration = 0;

  /// total permittable time duration of the slice
  duration_t span() const noexcept { return m_span; }

private:
  // non-const only to allow for history vector resizing
  duration_t m_span;

  friend class history_t;

  // end of slice, always an even number
  std::size_t tail = 0;
};

typedef std::vector<slice_t> slices_t;
typedef std::vector<duration_t> spans_t;
typedef std::vector<timestamp_t> timestamps_t;

typedef float rank_t;
typedef std::vector<rank_t> ranks_t;

enum error_t : uint8_t {
  ERROR_MULTICAST_PATH_PREFERENCE_UNSUPPORTED = 1
};

/// A sliced, sliding time window
class history_t {
public:
  /// Spans must be sorted in increasing order
  history_t(const spans_t &spans, uint8_t exponent = 7)
      : m_time_window(1 << exponent), m_head{/* stop */ m_time_window.size() -
                                             1} {
    assert(1 < exponent and exponent <= 12);
    assert(std::is_sorted(spans.begin(), spans.end()));
    for (auto span : spans) {
      m_slices.emplace_back(span);
    }
  }

  bool request_stop = false;

  /// Mark the time at which a property starts to hold
  void start(timestamp_t);

  /// Mark the time at which a property stops to hold
  void stop(timestamp_t);

  /// Reset each slice to its initial state
  void reset() noexcept;

  /// Make each slice start at the given point in time
  void refresh(timestamp_t) noexcept;

  timestamps_t timestamps(timestamp_t) const noexcept;

  /// Ordered according to their span, from shortest to longest
  const slices_t &slices() const noexcept { return m_slices; }

  /// Size is always be a power of two
  const timestamps_t &time_window() const noexcept { return m_time_window; }

private:
  friend class reach_summary_t;

  rank_t rank(const slice_t &, timestamp_t, timestamp_t) const noexcept;

  /// Index modulo length of time window
  std::size_t index(std::size_t i) const noexcept {
    return i & (m_time_window.size() - 1);
  }

  /// Newest start or stop time in the current time window
  timestamp_t newest_time() const noexcept { return m_time_window.at(m_head); }

  /// Oldest start time in the current time window
  timestamp_t oldest_start_time(const slice_t &slice) const {
    assert(!(slice.tail & 1));
    return m_time_window.at(slice.tail);
  }

  void update_duration(bool, timestamp_t);

  timestamps_t m_time_window;
  std::size_t m_head;
  slices_t m_slices;
};

typedef std::vector<history_t> history_vec_t;

class reach_summary_t {
public:
  const spans_t spans;
  const std::size_t number_of_nodes;
  timestamp_t global_start = std::numeric_limits<timestamp_t>::max(),
              global_stop = 0;
  reach_summary_t(std::size_t);
  reach_summary_t(const spans_t &, std::size_t);

  void reset() noexcept;
  void refresh(timestamp_t) noexcept;

  /// Ordered according to their span, from longest to shortest
  const slices_t &slices(flow_id_t, nid_t, nid_t) const;

  const history_t &history(flow_id_t, nid_t, nid_t) const;

  /// For each slice, normalized duration in which a property held
  ranks_t ranks(const history_t &) const;

  history_vec_t &history_vec(flow_id_t);
  history_t &history(flow_id_t, nid_t, nid_t);

private:
  typedef std::vector<history_vec_t> tensor_t;
  tensor_t m_tensor;

  inline std::size_t make_index(nid_t s, nid_t t) const {
    return number_of_nodes * s + t;
  }
};

/// A simple path in a directed graph
typedef std::vector<nid_t> path_t;

struct path_preference_t {
  flow_id_t flow_id;
  path_t x_path, y_path;
  rank_t rank;
  path_preference_t(flow_id_t f, path_t px, path_t py, rank_t r)
  : flow_id(f), x_path(px), y_path(py), rank(r) {}

  path_preference_t() : flow_id{0}, x_path{}, y_path{}, rank{0} {}
  path_preference_t(const path_preference_t &) = delete;
  // Cannot emplace struct into vector, see defect LWG #2089
  path_preference_t(path_preference_t &&) = default;
  path_preference_t& operator=(const path_preference_t &) = delete;
};

/// Start/stop information per path
typedef std::map<path_t, history_t> path_history_t;

/// Start/stop information per route (i.e., path + flow)
typedef std::vector<path_history_t> route_history_t;

/// Non-transitive preference relation measured by rank
typedef std::vector<path_preference_t> path_preferences_t;

/// Timestamps for each path in the network topology
typedef std::map<path_t, timestamps_t> path_timestamps_t;

/// Timestamps for each route (i.e., path + flow)
typedef std::vector<path_timestamps_t> route_timestamps_t;

class path_preference_summary_t {
public:
  timestamp_t global_stop = 0;

  path_preference_summary_t(const spans_t &spans, std::size_t number_of_nodes)
      : m_number_of_nodes{number_of_nodes}
      , m_link_history_vec(number_of_nodes * number_of_nodes,
          history_t(spans.empty() ? spans_t() : spans_t({spans.back()}))) {
    // Pick the longest span, since path preferences rely only on timestamps
    assert(std::is_sorted(spans.begin(), spans.end()));
  }

  path_history_t& path_history(const_flow_t flow) {
    if (flow->id >= m_route_history.size()) {
      m_route_history.resize((flow->id + 1) << 1);
    }
    assert(flow->id < m_route_history.size());
    return m_route_history[flow->id];
  }

  void link_up(nid_t source, nid_t target, timestamp_t);
  void link_down(nid_t source, nid_t target, timestamp_t);

  path_preferences_t path_preferences() const;

  /// \internal Use for testing only
  route_timestamps_t get_route_timestamps() const;

  /// \internal Use for testing only
  path_timestamps_t get_path_timestamps() const;

  timestamps_t link_timestamps(nid_t s, nid_t t) const {
    return m_link_history_vec.at(make_index(s, t)).timestamps(global_stop);
  }

private:
  const std::size_t m_number_of_nodes;
  history_vec_t m_link_history_vec;
  route_history_t m_route_history;

  inline std::size_t make_index(nid_t s, nid_t t) const {
    return m_number_of_nodes * s + t;
  }
};

class analysis_t {
public:
  constexpr static std::size_t MAX_NUMBER_OF_NODES = 4096;

  analysis_t(std::size_t number_of_nodes)
      : m_reach_summary{spans_t{}, number_of_nodes}
      , m_path_preference_summary{spans_t{}, number_of_nodes} {}

  analysis_t(const spans_t &spans, std::size_t number_of_nodes)
      : m_reach_summary{spans, number_of_nodes}
      , m_path_preference_summary{spans, number_of_nodes} {}

  /// Returns true when a new rule has been created; false otherwise
  bool insert_or_assign(const ip_prefix_t &, source_t, const target_t &,
                        timestamp_t current = 0);

  /// Returns true if the rule existed; false otherwise
  bool erase(const ip_prefix_t &, source_t, timestamp_t current = 0);

  void link_up(nid_t source, nid_t target, timestamp_t);
  void link_down(nid_t source, nid_t target, timestamp_t);

  bool ok() const noexcept { return m_loops_per_flow.empty(); }

  const flow_graph_t &flow_graph() const noexcept { return m_flow_graph; }

  void reset_reach_summary() noexcept { m_reach_summary.reset(); }

  void refresh_reach_summary(timestamp_t timestamp) noexcept {
    m_reach_summary.refresh(timestamp);
  }

  const reach_summary_t &reach_summary() const noexcept {
    return m_reach_summary;
  }

  path_preferences_t path_preferences() const noexcept {
    return m_path_preference_summary.path_preferences();
  }

  timestamps_t link_timestamps(nid_t s, nid_t t) const {
    return m_path_preference_summary.link_timestamps(s, t);
  }

  const path_preference_summary_t &path_preference_summary() const noexcept {
    return m_path_preference_summary;
  }

  const loops_per_flow_t &loops_per_flow() const noexcept {
    return m_loops_per_flow;
  }

  const affected_flows_t &affected_flows() const noexcept {
    return m_affected_flows;
  }

private:
  void clean_up();
  void update_reach_summary(timestamp_t);
  void update_global_timestamps(timestamp_t);

  flow_graph_t m_flow_graph;
  affected_flows_t m_affected_flows;
  loops_per_flow_t m_loops_per_flow;
  reach_summary_t m_reach_summary;
  path_preference_summary_t m_path_preference_summary;
};

timestamps_t intersect(const timestamps_t &, const timestamps_t &);

} // namespace nopticon
