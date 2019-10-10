// Copyright 2018 Alex Horn. All rights reserved.
// Use of this source code is governed by a LICENSE.

#define RAPIDJSON_HAS_STDSTRING 1

#include <rapidjson/document.h>
#include <rapidjson/filereadstream.h>
#include <rapidjson/ostreamwrapper.h>
#include <rapidjson/writer.h>

#include <fstream>
#include <iostream>
#include <unordered_map>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>

#include <nopticon.hh>

#define MILLISECONDS_PER_SECOND 1000

typedef std::unordered_map<std::string, nopticon::nid_t> string_to_nid_t;
typedef std::vector<std::string> nid_to_name_t;

std::string ipv4_format(nopticon::ip_addr_t ip_addr) {
  std::ostringstream sstream;
  for (signed char i = 3; i != 0; --i) {
    sstream << static_cast<unsigned>(
                   static_cast<uint8_t>(ip_addr >> (i * __CHAR_BIT__)))
            << '.';
  }
  sstream << static_cast<unsigned>(static_cast<uint8_t>(ip_addr));
  return sstream.str();
}

std::string ipv4_format(const nopticon::ip_prefix_t &ip_prefix) {
  std::ostringstream sstream;
  sstream << ip_prefix;
  return sstream.str();
}

class log_t {
public:
  log_t(std::streambuf *buffer, const nid_to_name_t &nid_to_name,
        unsigned opt_verbosity, bool opt_node_ids, float opt_rank_threshold,
        const nopticon::spans_t opt_reach_summary_spans)
      : m_ostream(buffer), m_nid_to_name(nid_to_name),
        m_opt_node_ids{opt_node_ids}, m_opt_rank_threshold{opt_rank_threshold},
        m_opt_verbosity{opt_verbosity}, m_opt_reach_summary_spans{
                                            opt_reach_summary_spans} {}

  void print(const nopticon::analysis_t &);

  const nopticon::spans_t &opt_reach_summary_spans() const noexcept {
    return m_opt_reach_summary_spans;
  }

private:
  friend void process_cmd(nopticon::analysis_t &, log_t &, rapidjson::Document &);

  typedef rapidjson::Writer<rapidjson::StringBuffer> writer_t;

  void print_flows(writer_t &, const nopticon::flow_tree_t &) const;
  void print_flows(writer_t &, const nopticon::affected_flows_t &) const;
  void print_flow(writer_t &, const nopticon::const_flow_t) const;

  void print_errors(writer_t &, const nopticon::loops_per_flow_t &) const;

  void print_reach_summary(writer_t &, const nopticon::flow_tree_t &,
                             const nopticon::reach_summary_t &) const;
  void print_reach_summary(writer_t &, const nopticon::affected_flows_t &,
                             const nopticon::reach_summary_t &) const;
  void print_reach_summary(writer_t &, const nopticon::const_flow_t,
                             const nopticon::reach_summary_t &) const;

  void print_nid(writer_t &, nopticon::nid_t) const;

  std::ostream m_ostream;
  const nid_to_name_t &m_nid_to_name;

  bool m_opt_node_ids;
  float m_opt_rank_threshold;
  unsigned m_opt_verbosity;
  nopticon::spans_t m_opt_reach_summary_spans;
};

void log_t::print_nid(writer_t &writer, nopticon::nid_t nid) const {
  if (m_opt_node_ids) {
    writer.Uint(nid);
  } else {
    writer.String(m_nid_to_name.at(nid));
  }
}

void log_t::print_flow(writer_t &writer,
                       const nopticon::const_flow_t flow) const {
  assert(flow != nullptr);
  if (flow->is_empty()) {
    return;
  }
  const auto &map = flow->data;
  if (map.empty()) {
    return;
  }
  writer.StartObject();
  writer.Key("flow");
  writer.String(ipv4_format(flow->ip_prefix));
  writer.Key("ranges");
  writer.StartArray();
  auto ranges = disjoint_ranges(flow);
  for (auto &range : ranges) {
    writer.StartObject();
    writer.Key("low");
    writer.String(ipv4_format(range.low));
    writer.Key("high");
    writer.String(ipv4_format(range.high));
    writer.EndObject();
  }
  writer.EndArray();
  writer.Key("links");
  writer.StartArray();
  for (auto &kv : map) {
    writer.StartObject();
    writer.Key("source");
    print_nid(writer, kv.first);
    writer.Key("target");
    writer.StartArray();
    for (auto &t : kv.second->target) {
      print_nid(writer, t);
    }
    writer.EndArray();
    writer.EndObject();
  }
  writer.EndArray();
  writer.EndObject();
}

void log_t::print_flows(
    writer_t &writer, const nopticon::affected_flows_t &affected_flows) const {
  writer.Key("flows");
  writer.StartArray();
  for (auto flow : affected_flows) {
    print_flow(writer, flow);
  }
  writer.EndArray();
}

void log_t::print_flows(writer_t &writer,
                        const nopticon::flow_tree_t &flow_tree) const {
  writer.Key("flows");
  writer.StartArray();
  auto flow_tree_iter = flow_tree.iter();
  do {
    auto flow = flow_tree_iter.ptr();
    print_flow(writer, flow);
  } while (flow_tree_iter.next());
  writer.EndArray();
}

void log_t::print_reach_summary(
    writer_t &writer, const nopticon::const_flow_t flow,
    const nopticon::reach_summary_t &reach_summary) const {
  static constexpr const char *const s_rank_strings[] = {
      "rank-0", "rank-1", "rank-2", "rank-3", "rank-4",
      "rank-5", "rank-6", "rank-7", "rank-8", "rank-9"};
  static constexpr std::size_t s_rank_strings_len =
      sizeof(s_rank_strings) / sizeof(s_rank_strings[0]);

  assert(flow != nullptr);
  if (flow->is_empty()) {
    return;
  }

  bool is_empty = true;
  for (nopticon::nid_t s = 0; s < m_nid_to_name.size(); ++s) {
    for (nopticon::nid_t t = 0; t < m_nid_to_name.size(); ++t) {
      if (s == t) {
        continue;
      }
      auto &history = reach_summary.history(flow->id, s, t);
      auto &slices = history.slices();
      if (slices.empty()) {
        continue;
      }
      auto ranks = reach_summary.ranks(history);
      if (slices.size() == 2) {
        assert(ranks.size() == 2);
        auto distance = std::fabs(ranks.front() - ranks.back());
        if (distance < m_opt_rank_threshold) {
          continue;
        }
      }
      bool non_zero_rank = false;
      for (auto rank : ranks) {
        if (rank != 0.0f) {
          non_zero_rank = true;
        }
      }
      if (not non_zero_rank) {
        continue;
      }
      if (is_empty) {
        writer.StartObject();
        writer.Key("flow");
        writer.String(ipv4_format(flow->ip_prefix));
        writer.Key("edges");
        writer.StartArray();
        is_empty = false;
      }
      writer.StartObject();
      writer.Key("source");
      print_nid(writer, s);
      writer.Key("target");
      print_nid(writer, t);
      writer.Key("can-be-direct");
      writer.Bool(history.can_be_direct);
      unsigned rank_id = 0;
      for (auto rank : ranks) {
        assert(rank_id < s_rank_strings_len);
        writer.Key(s_rank_strings[rank_id++]);
        writer.Double(rank);
      }
      if (m_opt_verbosity >= 8) {
        writer.Key("history");
        writer.StartArray();
        auto timestamps = history.timestamps(reach_summary.global_stop);
        for (auto timestamp : timestamps) {
          writer.Uint64(timestamp);
        }
        writer.EndArray();
      }
      writer.EndObject();
    }
  }
  if (not is_empty) {
    writer.EndArray();
    writer.EndObject();
  }
}

void log_t::print_reach_summary(
    writer_t &writer, const nopticon::flow_tree_t &flow_tree,
    const nopticon::reach_summary_t &reach_summary) const {
  auto flow_tree_iter = flow_tree.iter();
  writer.Key("reach-summary");
  writer.StartArray();
  do {
    auto flow = flow_tree_iter.ptr();
    print_reach_summary(writer, flow, reach_summary);
  } while (flow_tree_iter.next());
  writer.EndArray();
}

void log_t::print_reach_summary(
    writer_t &writer, const nopticon::affected_flows_t &affected_flows,
    const nopticon::reach_summary_t &reach_summary) const {
  writer.Key("reach-summary");
  writer.StartArray();
  for (auto flow : affected_flows) {
    print_reach_summary(writer, flow, reach_summary);
  }
  writer.EndArray();
}

void log_t::print_errors(
    writer_t &writer, const nopticon::loops_per_flow_t &loops_per_flow) const {
  bool is_empty = true;
  // order of reported flows is non-deterministic
  for (auto &pair : loops_per_flow) {
    if (pair.second.empty()) {
      continue;
    }
    if (is_empty) {
      writer.Key("errors");
      writer.StartArray();
      is_empty = false;
    }
    auto flow = pair.first;
    writer.StartObject();
    writer.Key("flow");
    writer.String(ipv4_format(flow->ip_prefix));
    writer.Key("forwarding-loops");
    writer.StartArray();
    for (auto &loop : pair.second) {
      writer.StartArray();
      for (auto nid : loop) {
        print_nid(writer, nid);
      }
      writer.EndArray();
    }
    writer.EndArray();
    writer.EndObject();
  }
  if (not is_empty) {
    writer.EndArray();
  }
}

void log_t::print(const nopticon::analysis_t &analysis) {
  rapidjson::StringBuffer s;
  writer_t writer{s};
  writer.StartObject();
  if (m_opt_node_ids) {
    writer.Key("nodes");
    writer.StartArray();
    for (nopticon::nid_t nid = 0; nid < m_nid_to_name.size(); ++nid) {
      writer.StartObject();
      writer.Key("id");
      writer.Uint(nid);
      writer.Key("name");
      writer.String(m_nid_to_name[nid]);
      writer.EndObject();
    }
    writer.EndArray();
  }
  if (not m_opt_reach_summary_spans.empty()) {
    if (m_opt_verbosity >= 7) {
      print_reach_summary(writer, analysis.flow_graph().flow_tree(),
                            analysis.reach_summary());
    } else if (m_opt_verbosity >= 5) {
      print_reach_summary(writer, analysis.affected_flows(),
                            analysis.reach_summary());
    }
  }
  if (m_opt_verbosity >= 6) {
    print_flows(writer, analysis.flow_graph().flow_tree());
  } else if (m_opt_verbosity >= 4) {
    print_flows(writer, analysis.affected_flows());
  }
  if (m_opt_verbosity >= 1) {
    print_errors(writer, analysis.loops_per_flow());
  }
  writer.EndObject();
  if (s.GetLength() > 2) {
    // longer than "{}"
    m_ostream << s.GetString() << std::endl;
  }
}

/// \post every nid is strictly less than `name_to_nid.size()`
int read_rdns(FILE *file, string_to_nid_t &name_to_nid,
              string_to_nid_t &ip_to_nid) {
  assert(file != nullptr);
  nopticon::nid_t nid = 0;
  char read_buffer[std::numeric_limits<uint16_t>::max()];
  rapidjson::FileReadStream input(file, read_buffer, sizeof(read_buffer));
  rapidjson::Document document;
  document.ParseStream(input);
  if (document.HasParseError()) {
    std::cerr << "Malformed rDNS JSON object" << std::endl;
    return EXIT_FAILURE;
  }
  if (not document.HasMember("routers")) {
    std::cerr << "Expected 'routers' array in top-level rDNS object"
              << std::endl;
    return EXIT_FAILURE;
  }
  for (auto &router : document["routers"].GetArray()) {
    if (not router.HasMember("name")) {
      std::cerr << "Expected 'name' field in each rDNS object" << std::endl;
      return EXIT_FAILURE;
    }
    auto name = router["name"].GetString();
    if (not router.HasMember("ifaces")) {
      std::cerr << "Expected 'ifaces' array in each rDNS object" << std::endl;
      return EXIT_FAILURE;
    }
    for (auto &iface : router["ifaces"].GetArray()) {
      auto ip_addr = iface.GetString();
      auto iter = name_to_nid.find(name);
      if (iter != name_to_nid.end()) {
        ip_to_nid[ip_addr] = iter->second;
      } else {
        ip_to_nid[ip_addr] = name_to_nid[name] = nid++;
      }
    }
  }
  assert(nid == name_to_nid.size());
  return EXIT_SUCCESS;
}

nopticon::ip_prefix_t make_ip_prefix(const std::string &ip_prefix) {
  assert(ip_prefix.find('/') != std::string::npos);
  std::istringstream istream{ip_prefix};
  nopticon::ip_addr_t ip_addr = 0;
  uint16_t byte;
  for (;;) {
    istream >> byte;
    assert(byte <= std::numeric_limits<uint8_t>::max());
    ip_addr |= byte;
    if (istream.peek() == '/') {
      istream.ignore();
      istream >> byte;
      assert(byte <= nopticon::ip_prefix_t::MAX_LEN);
      return nopticon::ip_prefix_t{ip_addr, static_cast<uint8_t>(byte)};
    }
    istream.ignore();
    ip_addr <<= __CHAR_BIT__;
  }
  return {};
}

enum class cmd_t : uint8_t {
  PRINT_LOG = 0,
  RESET_NETWORK_SUMMARY,
  REFRESH_NETWORK_SUMMARY,
};

void process_cmd(nopticon::analysis_t &analysis, log_t &log,
                 rapidjson::Document &document) {
  assert(document["Command"].HasMember("Opcode"));
  assert(document["Command"]["Opcode"].IsUint());
  unsigned highest_verbosity;
  nopticon::timestamp_t timestamp;
  auto opcode = document["Command"]["Opcode"].GetUint();
  auto cmd = static_cast<cmd_t>(opcode);
  switch (cmd) {
  case cmd_t::PRINT_LOG:
    highest_verbosity = 8;
    std::swap(log.m_opt_verbosity, highest_verbosity);
    log.print(analysis);
    std::swap(log.m_opt_verbosity, highest_verbosity);
    break;
  case cmd_t::RESET_NETWORK_SUMMARY:
    analysis.reset_reach_summary();
    break;
  case cmd_t::REFRESH_NETWORK_SUMMARY:
    assert(document["Command"].HasMember("Timestamp"));
    if (document["Command"]["Timestamp"].IsUint64()) {
        // Convert time in seconds to time in milliseconds
        timestamp = document["Command"]["Timestamp"].GetUint64()
            * MILLISECONDS_PER_SECOND;
    } else {
        // Convert time in seconds and nanoseconds to time in milliseconds
        assert(document["Command"]["Timestamp"].IsDouble());
        timestamp = static_cast<nopticon::timestamp_t>(
                document["Command"]["Timestamp"].GetDouble()
                * MILLISECONDS_PER_SECOND);
    }
    analysis.refresh_reach_summary(timestamp);
    break;
  default:
    std::cerr << "Unsupported gobgp-analysis command: "
              << static_cast<unsigned>(cmd) << std::endl;
  }
}

void process_bmp_message(std::size_t number_of_nodes, FILE *file,
                         const string_to_nid_t &ip_to_nid, log_t &log) {
  assert(file != nullptr);
  nopticon::analysis_t analysis{log.opt_reach_summary_spans(),
                                number_of_nodes};
  char read_buffer[std::numeric_limits<uint16_t>::max()];
  rapidjson::FileReadStream input(file, read_buffer, sizeof(read_buffer));
  rapidjson::Document document;
  while (not document.ParseStream<rapidjson::kParseStopWhenDoneFlag>(input)
                 .HasParseError()) {
    if (document.HasMember("Command")) {
      process_cmd(analysis, log, document);
      continue;
    }
    assert(document.HasMember("Header"));
    assert(document["Header"].HasMember("Type"));
    assert(document["Header"]["Type"].IsUint());

    auto &header = document["Header"];
    auto header_type = header["Type"].GetInt();
    if (header_type != 0) {
      continue;
    }

    assert(document.HasMember("PeerHeader"));
    assert(document["PeerHeader"].HasMember("PeerBGPID"));
    assert(document["PeerHeader"].HasMember("Timestamp"));
    assert(document.HasMember("Body"));
    assert(document["Body"].HasMember("BGPUpdate"));
    assert(document["Body"]["BGPUpdate"].HasMember("Body"));
    assert(document["Body"]["BGPUpdate"]["Body"].HasMember("PathAttributes"));
    assert(document["Body"]["BGPUpdate"]["Body"]["PathAttributes"].IsArray());
    assert(document["Body"]["BGPUpdate"]["Body"].HasMember("NLRI"));
    assert(document["Body"]["BGPUpdate"]["Body"]["NLRI"].IsArray());
    assert(document["Body"]["BGPUpdate"]["Body"].HasMember("WithdrawnRoutes"));
    assert(document["Body"]["BGPUpdate"]["Body"]["WithdrawnRoutes"].IsArray());

    auto &peer_header = document["PeerHeader"];
    auto peer_bgpid = peer_header["PeerBGPID"].GetString();
    nopticon::timestamp_t timestamp;
    if (peer_header["Timestamp"].IsUint64()) {
      // Convert time in seconds and to time in milliseconds
      timestamp = peer_header["Timestamp"].GetUint64() * MILLISECONDS_PER_SECOND;
    } else {
      // Convert time in seconds and nanoseconds to time in milliseconds
      assert(peer_header["Timestamp"].IsDouble());
      timestamp = static_cast<nopticon::timestamp_t>(
          peer_header["Timestamp"].GetDouble() * MILLISECONDS_PER_SECOND);
    }
    auto &body = document["Body"];
    auto &bgp_update = body["BGPUpdate"];
    auto &bgp_update_body = bgp_update["Body"];
    auto &path_attributes = bgp_update_body["PathAttributes"];
    std::string next_hop, ip_prefix;
    for (auto &path_attribute : path_attributes.GetArray()) {
      assert(path_attribute.HasMember("type"));
      assert(path_attribute["type"].IsUint());
      auto path_attribute_type = path_attribute["type"].GetUint();
      if (path_attribute_type != 3) {
        continue;
      }
      assert(path_attribute.HasMember("nexthop"));
      next_hop = path_attribute["nexthop"].GetString();
    }
    auto &nlri = bgp_update_body["NLRI"];
    assert(nlri.Empty() == next_hop.empty());
    auto source = ip_to_nid.at(peer_bgpid);
    if (next_hop != "0.0.0.0") {
      for (auto &nlri_value : nlri.GetArray()) {
        assert(nlri_value.HasMember("prefix"));
        auto ip_prefix = make_ip_prefix(nlri_value["prefix"].GetString());
        auto target = ip_to_nid.at(next_hop);
        analysis.insert_or_assign(ip_prefix, source, {target}, timestamp);
        log.print(analysis);
      }
    }
    auto &withdrawn_routes = bgp_update_body["WithdrawnRoutes"];
    assert(withdrawn_routes.Empty() != next_hop.empty());
    for (auto &withdrawn_route : withdrawn_routes.GetArray()) {
      assert(withdrawn_route.HasMember("prefix"));
      auto ip_prefix = make_ip_prefix(withdrawn_route["prefix"].GetString());
      analysis.erase(ip_prefix, source, timestamp);
      log.print(analysis);
    }
  }
}

static const char *const s_usage =
    "Usage: gobgp-analysis [OPTIONS] rDNS\n"
    "Logically analyze the data planes induced by BMP messages\n\n"
    "Usage example:\n\n"
    "  gobmpd | gobgp-analysis --verbosity 3 rdns.json\n\n"
    "rDNS: a JSON file that maps each router to its interfaces \n\n"
    "Example:\n\n"
    "  {\n"
    "      \"routers\": [\n"
    "          {\n"
    "              \"name\": \"someRouter\",\n"
    "              \"ifaces\": [\n"
    "                  \"10.0.0.1\",\n"
    "                  \"10.0.0.2\"\n"
    "              ]\n"
    "          },\n"
    "          {\n"
    "              \"name\": \"anotherRouter\",\n"
    "              \"ifaces\": [\n"
    "                  \"10.0.0.3\"\n"
    "              ]\n"
    "          }\n"
    "      ]\n"
    "  }\n\n"
    "OPTIONS:\n"
    "  --help\n"
    "  \tPrint out this usage information\n\n"
    "  --node-ids\n"
    "  \tPrint node identifiers in JSON output\n\n"
    "  --log FILE\n"
    "  \tOutput results to FILE instead of stdout\n\n"
    "  --reach-summary SPANS\n"
    "  \tAnalyze a history of data planes where\n"
    "  \tSPANS is a comma-separated list of durations,\n"
    "  \tdenoting the length of sliding time windows\n\n"
    "  --rank-threshold DISTANCE\n"
    "  \t(requires --reach-summary SPANS option)\n"
    "  \tIf network summary's |SPANS|=2, then report\n"
    "  \tonly those reachability properties whose\n"
    "  \tdifference in rank is greater than or equal\n"
    "  \tto DISTANCE, a value between 0.0 and 1.0\n\n"
    "  --verbosity VERBOSITY\n"
    "  \tAdjust the details included in the log where\n"
    "  \tVERBOSITY (from low to high) is as follows:\n"
    "  \t0 - perform analysis but produce no output\n"
    "  \t1 - BMP messages that cause forwarding loops\n"
    "  \t4 - ... and information about affected flows\n"
    "  \t5 - ... and network summary for affected flows\n"
    "  \t    (requires --reach-summary SPANS option)\n"
    "  \t6 - ... and information about all flows\n"
    "  \t7 - ... and network summary for all flows\n"
    "  \t    (requires --reach-summary SPANS option)\n"
    "  \t8 - ... and history of each inferred property\n";

void print_usage() { std::cerr << s_usage; }

void print_rdns_error() { std::cerr << "rDNS map is empty" << std::endl; }

std::string yes_or_not(bool flag) { return flag ? "yes" : "no"; }

template <class T> std::string join(const std::vector<T> &vec) {
  std::ostringstream sstream;
  std::copy(vec.begin(), vec.end(), std::ostream_iterator<T>(sstream, ","));
  return sstream.str();
}

int main(int argc, char **args) {
  const char *rdns_file_name = nullptr;
  const char *log_file_name = nullptr;
  bool opt_node_ids = false;
  float opt_rank_threshold = 0.0f;
  nopticon::spans_t opt_reach_summary_spans;
  unsigned opt_verbosity = 1;
  if (argc < 2) {
    print_usage();
    return EXIT_FAILURE;
  }
  if (std::strcmp(args[1], "--help") == 0) {
    print_usage();
    return EXIT_SUCCESS;
  }
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::strcmp(args[i], "--log") == 0) {
      log_file_name = args[i + 1];
    }
    if (std::strcmp(args[i], "--verbosity") == 0) {
      std::stringstream sstream{args[i + 1]};
      sstream >> opt_verbosity;
    }
    if (std::strcmp(args[i], "--node-ids") == 0) {
      opt_node_ids = true;
    }
    if (std::strcmp(args[i], "--rank-threshold") == 0) {
      std::stringstream sstream{args[i + 1]};
      sstream >> opt_rank_threshold;
      assert(0.0f <= opt_rank_threshold);
      assert(opt_rank_threshold <= 1.0f);
    }
    if (std::strcmp(args[i], "--reach-summary") == 0) {
      std::stringstream sstream{args[i + 1]};
      nopticon::duration_t span;
      while (sstream >> span) {
        opt_reach_summary_spans.push_back(span * MILLISECONDS_PER_SECOND);
        if (sstream.peek() == ',') {
          sstream.ignore();
        }
      }
      assert(not opt_reach_summary_spans.empty());
      std::sort(opt_reach_summary_spans.begin(),
                opt_reach_summary_spans.end());
    }
  }
  rdns_file_name = args[argc - 1];
  auto rdns_file = std::fopen(rdns_file_name, "r");
  if (!rdns_file) {
    std::perror("rDNS file opening failed");
    return EXIT_FAILURE;
  }
  string_to_nid_t name_to_nid, ip_to_nid;
  auto status = read_rdns(rdns_file, name_to_nid, ip_to_nid);
  fclose(rdns_file);
  if (status) {
    return status;
  }
  nid_to_name_t nid_to_name(name_to_nid.size());
  for (auto &pair : name_to_nid) {
    auto &name = nid_to_name.at(pair.second);
    assert(name.empty());
    name = pair.first;
  }
  if (ip_to_nid.empty()) {
    print_rdns_error();
    return EXIT_FAILURE;
  }

  std::streambuf *log_buffer;
  std::ofstream log_of;
  if (log_file_name != nullptr) {
    log_of.open(log_file_name);
    log_buffer = log_of.rdbuf();
  } else {
    log_buffer = std::cout.rdbuf();
  }

  std::cerr << "Nopticon version: " NOPTICON_VERSION "\n"
            << "enable node ids: " << yes_or_not(opt_node_ids) << std::endl
            << "log file: "
            << (log_file_name == nullptr ? "stdout" : log_file_name)
            << std::endl
            << "network summary spans: "
            << (opt_reach_summary_spans.empty()
                    ? "<empty>"
                    : join(opt_reach_summary_spans))
            << std::endl
            << "rank threshold: " << opt_rank_threshold << std::endl
            << "verbosity level: " << opt_verbosity << std::endl;
  log_t log{log_buffer,   nid_to_name,        opt_verbosity,
            opt_node_ids, opt_rank_threshold, opt_reach_summary_spans};
  process_bmp_message(nid_to_name.size(), stdin, ip_to_nid, log);
  return EXIT_SUCCESS;
}
