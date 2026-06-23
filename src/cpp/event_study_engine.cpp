#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <libpq-fe.h>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;

// Structures
struct MinuteBar {
  long long timestamp_ms;
  double open;
  double high;
  double low;
  double close;
  double volume;
};

struct TrumpPost {
  std::string timestamp_utc;
  long long timestamp_ms;
  std::string message;
  std::string source_url;
  std::string source_type;
};

// Convert parsed timestamp to seconds since Unix Epoch.
long long timestamp_to_s(int year, int month, int day, int hour, int min,
                         int sec) {
  static const int days_in_month[] = {31, 28, 31, 30, 31, 30,
                                      31, 31, 30, 31, 30, 31};

  int leap_days = 0;
  for (int y = 1970; y < year; ++y) {
    if ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0)) {
      leap_days++;
    }
  }

  long long days = (year - 1970) * 365 + leap_days;
  for (int m = 0; m < month - 1; ++m) {
    if (m == 1 && ((year % 4 == 0 && year % 100 != 0) || (year % 400 == 0))) {
      days += 29;
    } else {
      days += days_in_month[m];
    }
  }
  days += day - 1;

  return days * 86400LL + hour * 3600LL + min * 60LL + sec;
}

// Converts "YYYY-MM-DD HH:MM:SS" to milliseconds since Unix Epoch
long long utc_to_ms(const std::string &ts_str) {
  int year, month, day, hour = 0, min = 0, sec = 0;
  if (sscanf(ts_str.c_str(), "%d-%d-%d %d:%d:%d", &year, &month, &day, &hour,
             &min, &sec) < 3) {
    return -1;
  }
  return timestamp_to_s(year, month, day, hour, min, sec) * 1000LL;
}

std::unordered_map<std::string, std::string> load_env_file() {
  std::unordered_map<std::string, std::string> env;
  std::ifstream file("src/.env");
  if (!file.is_open()) {
    return env;
  }
  std::string line;
  while (std::getline(file, line)) {
    // Remove comments
    size_t comment_pos = line.find('#');
    if (comment_pos != std::string::npos) {
      line = line.substr(0, comment_pos);
    }

    // Find key=value
    size_t eq_pos = line.find('=');
    if (eq_pos == std::string::npos) {
      continue;
    }
    std::string key = line.substr(0, eq_pos);
    std::string value = line.substr(eq_pos + 1);

    // Helper to trim spaces and quotes
    auto trim_str = [](std::string &s) {
      s.erase(0, s.find_first_not_of(" \t\r\n\"'"));
      size_t last = s.find_last_not_of(" \t\r\n\"'");
      if (last != std::string::npos) {
        s.erase(last + 1);
      } else {
        s.clear();
      }
    };
    trim_str(key);
    trim_str(value);
    if (!key.empty()) {
      env[key] = value;
    }
  }
  return env;
}

PGconn *connect_db() {
  std::unordered_map<std::string, std::string> env = load_env_file();
  if (env.empty()) {
    std::cerr << "Error: Could not open src/.env file.\n";
    return nullptr;
  }

  std::string host = env["DB_HOST"];
  std::string port = env["DB_PORT"];
  std::string dbname = env["DB_NAME"];
  std::string user = env["DB_USER"];
  std::string password = env["DB_PASSWORD"];

  std::vector<std::string> parts;
  if (!host.empty())
    parts.push_back("host=" + host);
  if (!port.empty())
    parts.push_back("port=" + port);
  if (!dbname.empty())
    parts.push_back("dbname=" + dbname);
  if (!user.empty())
    parts.push_back("user=" + user);
  if (!password.empty())
    parts.push_back("password=" + password);

  if (parts.empty()) {
    std::cerr
        << "Error: No database connection details found in src/.env file.\n";
    return nullptr;
  }

  std::ostringstream oss;
  for (size_t i = 0; i < parts.size(); ++i) {
    // Join parts into single string with space between parts
    oss << parts[i] << (i + 1 < parts.size() ? " " : "");
  }
  std::string conninfo = oss.str();

  PGconn *conn = PQconnectdb(conninfo.c_str());
  if (PQstatus(conn) != CONNECTION_OK) {
    std::cerr << "Connection to database failed: " << PQerrorMessage(conn)
              << std::endl;
    PQfinish(conn);
    return nullptr;
  }
  return conn;
}

std::vector<MinuteBar>
load_asset_data_from_db(PGconn *conn, const std::string &asset,
                        const std::string &post_timestamp_utc) {
  std::vector<MinuteBar> bars;

  std::string date_query = "SELECT DISTINCT DATE(timestamp_utc) AS d "
                           "FROM market_data_1min "
                           "WHERE ticker = '" +
                           asset + "' AND timestamp_utc >= '" +
                           post_timestamp_utc +
                           "' "
                           "ORDER BY d LIMIT 3;";

  PGresult *res_dates = PQexec(conn, date_query.c_str());
  if (PQresultStatus(res_dates) != PGRES_TUPLES_OK) {
    std::cerr << "Query failed: " << PQerrorMessage(conn) << std::endl;
    PQclear(res_dates);
    return bars;
  }

  int num_dates = PQntuples(res_dates);
  if (num_dates == 0) {
    PQclear(res_dates);
    return bars;
  }

  std::string min_date = PQgetvalue(res_dates, 0, 0);
  std::string max_date = PQgetvalue(res_dates, num_dates - 1, 0);
  PQclear(res_dates);

  std::string bars_query =
      "SELECT timestamp_ms, open, high, low, close, volume "
      "FROM market_data_1min "
      "WHERE ticker = '" +
      asset +
      "' AND "
      "timestamp_utc >= '" +
      min_date +
      " 00:00:00' AND "
      "timestamp_utc <= '" +
      max_date +
      " 23:59:59' "
      "ORDER BY timestamp_utc;";

  PGresult *res_bars = PQexec(conn, bars_query.c_str());
  if (PQresultStatus(res_bars) != PGRES_TUPLES_OK) {
    std::cerr << "Query failed: " << PQerrorMessage(conn) << std::endl;
    PQclear(res_bars);
    return bars;
  }

  int num_bars = PQntuples(res_bars);
  for (int i = 0; i < num_bars; ++i) {
    MinuteBar bar;
    bar.timestamp_ms = std::stoll(PQgetvalue(res_bars, i, 0));
    bar.open = std::stod(PQgetvalue(res_bars, i, 1));
    bar.high = std::stod(PQgetvalue(res_bars, i, 2));
    bar.low = std::stod(PQgetvalue(res_bars, i, 3));
    bar.close = std::stod(PQgetvalue(res_bars, i, 4));
    bar.volume = std::stod(PQgetvalue(res_bars, i, 5));
    bars.push_back(bar);
  }

  PQclear(res_bars);
  return bars;
}

// Find the closest price to a target timestamp.
double find_price_at(const std::vector<MinuteBar> &bars, long long target_ms,
                     long long tolerance_ms, size_t &found_idx) {
  auto it = std::lower_bound(bars.begin(), bars.end(), target_ms,
                             [](const MinuteBar &bar, long long val) {
                               return bar.timestamp_ms < val;
                             });

  if (it == bars.end()) {
    if (!bars.empty()) {
      auto last_it = std::prev(bars.end());
      long long diff = std::abs(last_it->timestamp_ms - target_ms);
      if (diff <= tolerance_ms) {
        found_idx = std::distance(bars.begin(), last_it);
        return last_it->close;
      }
    }
    return -1.0;
  }

  long long diff = std::abs(it->timestamp_ms - target_ms);
  size_t best_idx = std::distance(bars.begin(), it);
  double best_price = it->close;
  long long min_diff = diff;

  if (it != bars.begin()) {
    auto prev_it = std::prev(it);
    long long prev_diff = std::abs(prev_it->timestamp_ms - target_ms);
    if (prev_diff < min_diff) {
      min_diff = prev_diff;
      best_idx = std::distance(bars.begin(), prev_it);
      best_price = prev_it->close;
    }
  }

  if (min_diff <= tolerance_ms) {
    found_idx = best_idx;
    return best_price;
  }
  return -1.0;
}

// Calculate volatility
double compute_volatility(const std::vector<MinuteBar> &bars, size_t start_idx,
                          size_t end_idx) {
  if (end_idx <= start_idx || end_idx >= bars.size())
    return -1.0;

  std::vector<double> returns;
  for (size_t i = start_idx + 1; i <= end_idx; ++i) {
    double prev_close = bars[i - 1].close;
    if (prev_close > 0.0) {
      double ret = (bars[i].close - prev_close) / prev_close;
      returns.push_back(ret);
    }
  }

  if (returns.size() < 2)
    return -1.0;

  double sum = 0.0;
  for (double r : returns)
    sum += r;
  double mean = sum / returns.size();

  double sq_sum = 0.0;
  for (double r : returns) {
    sq_sum += (r - mean) * (r - mean);
  }

  double std_dev = std::sqrt(sq_sum / (returns.size() - 1));
  return std_dev / std::sqrt(returns.size());
}

std::string escape_sql_string(const std::string &str) {
  std::string result;
  for (char c : str) {
    if (c == '\'') {
      result += "''";
    } else {
      result += c;
    }
  }
  return result;
}

// Calculate Beta
std::optional<double> compute_beta(const std::vector<MinuteBar> &asset_bars,
                                   size_t asset_start_idx, size_t asset_end_idx,
                                   const std::vector<MinuteBar> &bench_bars) {
  if (asset_end_idx <= asset_start_idx || asset_end_idx >= asset_bars.size())
    return std::nullopt;

  long long t_start = asset_bars[asset_start_idx].timestamp_ms;
  long long t_end = asset_bars[asset_end_idx].timestamp_ms;

  auto bench_start_it =
      std::lower_bound(bench_bars.begin(), bench_bars.end(), t_start,
                       [](const MinuteBar &bar, long long val) {
                         return bar.timestamp_ms < val;
                       });
  auto bench_end_it =
      std::lower_bound(bench_bars.begin(), bench_bars.end(), t_end,
                       [](const MinuteBar &bar, long long val) {
                         return bar.timestamp_ms < val;
                       });

  if (bench_start_it == bench_bars.end())
    return std::nullopt;

  std::unordered_map<long long, double> asset_closes;
  for (size_t i = asset_start_idx; i <= asset_end_idx; ++i) {
    asset_closes[asset_bars[i].timestamp_ms] = asset_bars[i].close;
  }

  std::vector<std::pair<double, double>> aligned_returns;

  for (auto it = bench_start_it; it != bench_end_it && it != bench_bars.end();
       ++it) {
    if (it == bench_bars.begin())
      continue;
    auto prev_it = std::prev(it);

    long long t_curr = it->timestamp_ms;
    long long t_prev = prev_it->timestamp_ms;

    if (t_curr - t_prev > 65000)
      continue;

    if (asset_closes.count(t_curr) && asset_closes.count(t_prev)) {
      double prev_asset_price = asset_closes[t_prev];
      double prev_bench_price = prev_it->close;
      if (prev_asset_price > 0.0 && prev_bench_price > 0.0) {
        double asset_ret =
            (asset_closes[t_curr] - prev_asset_price) / prev_asset_price;
        double bench_ret = (it->close - prev_bench_price) / prev_bench_price;
        aligned_returns.push_back({asset_ret, bench_ret});
      }
    }
  }

  if (aligned_returns.size() < 2)
    return std::nullopt;

  double sum_asset = 0.0, sum_bench = 0.0;
  for (const auto &p : aligned_returns) {
    sum_asset += p.first;
    sum_bench += p.second;
  }
  double mean_asset = sum_asset / aligned_returns.size();
  double mean_bench = sum_bench / aligned_returns.size();

  double cov = 0.0;
  double var_bench = 0.0;
  for (const auto &p : aligned_returns) {
    cov += (p.first - mean_asset) * (p.second - mean_bench);
    var_bench += (p.second - mean_bench) * (p.second - mean_bench);
  }

  double variance_bench = var_bench / (aligned_returns.size() - 1);
  if (variance_bench < 1e-8 || std::isnan(variance_bench) || std::isnan(cov))
    return std::nullopt;
  return cov / var_bench;
}

int main(int argc, char *argv[]) {
  std::string benchmark_asset = "ES";

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--benchmark" && i + 1 < argc) {
      benchmark_asset = argv[++i];
    } else if (arg == "--help" || arg == "-h") {
      std::cout << "Usage: event_engine.exe [options]\n"
                << "Options:\n"
                << "  --benchmark <asset>   Market benchmark asset name "
                   "(default: ES)\n";
      return 0;
    }
  }

  std::cout << "Starting Event Study Calculation...\n";
  std::cout << "Benchmark Asset: " << benchmark_asset << "\n\n";

  PGconn *conn = connect_db();
  if (!conn) {
    return 1;
  }

  // Parse Trump posts directly from database
  std::cout << "Loading Trump posts from PostgreSQL...\n";
  std::string posts_query =
      "SELECT timestamp_utc, message, source_url, source_type "
      "FROM trump_posts "
      "WHERE topic IS NOT NULL AND topic != 'Miscellaneous' "
      "ORDER BY timestamp_utc;";

  PGresult *res_posts = PQexec(conn, posts_query.c_str());
  if (PQresultStatus(res_posts) != PGRES_TUPLES_OK) {
    std::cerr << "Error loading posts: " << PQerrorMessage(conn) << "\n";
    PQclear(res_posts);
    PQfinish(conn);
    return 1;
  }

  int num_posts = PQntuples(res_posts);
  std::vector<TrumpPost> posts;
  for (int i = 0; i < num_posts; ++i) {
    TrumpPost p;
    p.timestamp_utc = PQgetvalue(res_posts, i, 0);
    if (p.timestamp_utc.find('.') != std::string::npos) {
      p.timestamp_utc = p.timestamp_utc.substr(0, p.timestamp_utc.find('.'));
    }
    p.timestamp_ms = utc_to_ms(p.timestamp_utc);
    if (p.timestamp_ms == -1)
      continue;
    p.message = PQgetvalue(res_posts, i, 1);
    p.source_url = PQgetvalue(res_posts, i, 2);
    p.source_type = PQgetvalue(res_posts, i, 3);
    posts.push_back(p);
  }
  PQclear(res_posts);

  std::cout << "Loaded " << posts.size() << " valid posts.\n";

  // Asset list
  std::vector<std::string> assets = {"I_NDX", "X_BTCUSD", "CL",
                                     "ES",    "YM",       "ZN"};

  // Event Study Time Intervals (1m, 5m, 15m, 30m, 1h, 1d)
  const int num_intervals = 6;
  std::string interval_names[num_intervals] = {"1m",  "5m", "15m",
                                               "30m", "1h", "1d"};
  long long interval_ms[num_intervals] = {
      60 * 1000LL,          // 1 min
      5 * 60 * 1000LL,      // 5 min
      15 * 60 * 1000LL,     // 15 min
      30 * 60 * 1000LL,     // 30 min
      60 * 60 * 1000LL,     // 1 hour
      24 * 60 * 60 * 1000LL // 1 day
  };

  long long interval_tolerance_ms[num_intervals] = {
      30 * 1000LL,     // 1m: 30 sec tolerance
      60 * 1000LL,     // 5m: 1 min tolerance
      2 * 60 * 1000LL, // 15m: 2 min tolerance
      3 * 60 * 1000LL, // 30m: 3 min tolerance
      5 * 60 * 1000LL, // 1h: 5 min tolerance
      30 * 60 * 1000LL // 1d: 30 min tolerance
  };

  // Start database transaction to bundle all commands into one transaction
  PQexec(conn, "BEGIN;");

  // Create table if not exists (just to make sure table is present)
  PQexec(conn, "CREATE TABLE IF NOT EXISTS event_study_results ("
               "timestamp_utc TIMESTAMP, "
               "message_snippet TEXT, "
               "asset TEXT, "
               "baseline_price REAL, "
               "baseline_time_offset_sec REAL, "
               "return_1m REAL, return_5m REAL, return_15m REAL, return_30m "
               "REAL, return_1h REAL, return_1d REAL, "
               "vol_1m REAL, vol_5m REAL, vol_15m REAL, vol_30m REAL, vol_1h "
               "REAL, vol_1d REAL, "
               "beta_1m REAL, beta_5m REAL, beta_15m REAL, beta_30m REAL, "
               "beta_1h REAL, beta_1d REAL, "
               "PRIMARY KEY (timestamp_utc, asset)"
               ");");

  // Process posts
  size_t processed_count = 0;
  auto start_time = std::chrono::high_resolution_clock::now();

  for (size_t post_idx = 0; post_idx < posts.size(); ++post_idx) {
    const auto &post = posts[post_idx];

    // Load benchmark data (ES) for this post
    auto bench_bars =
        load_asset_data_from_db(conn, benchmark_asset, post.timestamp_utc);

    // Load all assets' data for this post
    for (const auto &asset : assets) {
      auto asset_bars =
          load_asset_data_from_db(conn, asset, post.timestamp_utc);

      if (asset_bars.empty())
        continue;

      size_t start_idx = 0;
      double p0 = find_price_at(asset_bars, post.timestamp_ms, 15 * 60 * 1000LL,
                                start_idx);

      if (p0 <= 0.0) {
        continue;
      }

      long long t0 = asset_bars[start_idx].timestamp_ms;
      double baseline_offset_sec = (t0 - post.timestamp_ms) / 1000.0;

      double returns[num_intervals] = {-1.0, -1.0, -1.0, -1.0, -1.0, -1.0};
      double vols[num_intervals] = {-1.0, -1.0, -1.0, -1.0, -1.0, -1.0};
      std::optional<double>
          betas[num_intervals]; // default value is std::nullopt

      for (int w = 0; w < num_intervals; ++w) {
        long long target_ms = t0 + interval_ms[w];
        size_t end_idx = 0;
        double p_target = find_price_at(asset_bars, target_ms,
                                        interval_tolerance_ms[w], end_idx);

        if (p_target > 0.0 && p0 > 0.0) {
          returns[w] = (p_target - p0) / p0;
          vols[w] = compute_volatility(asset_bars, start_idx, end_idx);

          if (asset == benchmark_asset) {
            betas[w] = 1.0;
          } else if (!bench_bars.empty()) {
            betas[w] = compute_beta(asset_bars, start_idx, end_idx, bench_bars);
          }
        }
      }

      std::string msg_snippet = post.message;
      msg_snippet.erase(
          std::remove(msg_snippet.begin(), msg_snippet.end(), '\n'),
          msg_snippet.end());
      msg_snippet.erase(
          std::remove(msg_snippet.begin(), msg_snippet.end(), '\r'),
          msg_snippet.end());
      msg_snippet.erase(
          std::remove(msg_snippet.begin(), msg_snippet.end(), '"'),
          msg_snippet.end());
      if (msg_snippet.length() > 50) {
        msg_snippet = msg_snippet.substr(0, 47) + "...";
      }

      // Format SQL query for upsert of returns, volatilities, and betas
      std::ostringstream sql;
      sql << "INSERT INTO event_study_results ("
          << "timestamp_utc, message_snippet, asset, baseline_price, "
             "baseline_time_offset_sec, "
          << "return_1m, return_5m, return_15m, return_30m, return_1h, "
             "return_1d, "
          << "vol_1m, vol_5m, vol_15m, vol_30m, vol_1h, vol_1d, "
          << "beta_1m, beta_5m, beta_15m, beta_30m, beta_1h, beta_1d"
          << ") VALUES ("
          << "'" << post.timestamp_utc << "', "
          << "'" << escape_sql_string(msg_snippet) << "', "
          << "'" << asset << "', " << p0 << ", " << baseline_offset_sec << ", ";

      // returns
      for (int w = 0; w < num_intervals; ++w) {
        if (returns[w] == -1.0 && vols[w] == -1.0)
          sql << "NULL, ";
        else
          sql << returns[w] << ", ";
      }
      // vols
      for (int w = 0; w < num_intervals; ++w) {
        if (vols[w] == -1.0)
          sql << "NULL, ";
        else
          sql << vols[w] << ", ";
      }
      // betas
      for (int w = 0; w < num_intervals; ++w) {
        if (!betas[w].has_value())
          sql << "NULL" << (w == num_intervals - 1 ? "" : ", ");
        else
          sql << betas[w].value() << (w == num_intervals - 1 ? "" : ", ");
      }
      sql << ") ON CONFLICT (timestamp_utc, asset) DO UPDATE SET "
          << "message_snippet = EXCLUDED.message_snippet, "
          << "baseline_price = EXCLUDED.baseline_price, "
          << "baseline_time_offset_sec = EXCLUDED.baseline_time_offset_sec, "
          << "return_1m = EXCLUDED.return_1m, return_5m = EXCLUDED.return_5m, "
             "return_15m = EXCLUDED.return_15m, return_30m = "
             "EXCLUDED.return_30m, return_1h = EXCLUDED.return_1h, return_1d = "
             "EXCLUDED.return_1d, "
          << "vol_1m = EXCLUDED.vol_1m, vol_5m = EXCLUDED.vol_5m, vol_15m = "
             "EXCLUDED.vol_15m, vol_30m = EXCLUDED.vol_30m, vol_1h = "
             "EXCLUDED.vol_1h, vol_1d = EXCLUDED.vol_1d, "
          << "beta_1m = EXCLUDED.beta_1m, beta_5m = EXCLUDED.beta_5m, beta_15m "
             "= EXCLUDED.beta_15m, beta_30m = EXCLUDED.beta_30m, beta_1h = "
             "EXCLUDED.beta_1h, beta_1d = EXCLUDED.beta_1d;";

      PGresult *res_ins = PQexec(conn, sql.str().c_str());
      PQclear(res_ins);
    }

    processed_count++;
    if (processed_count % 100 == 0 || processed_count == posts.size()) {
      auto curr_time = std::chrono::high_resolution_clock::now();
      auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(
                          curr_time - start_time)
                          .count();
      std::cout << "Processed " << processed_count << " / " << posts.size()
                << " posts (" << (processed_count * 100 / posts.size())
                << "%), Time: " << duration / 1000.0 << "s\n";
    }
  }

  PQexec(conn, "COMMIT;");
  PQfinish(conn);
  std::cout << "\nEvent study analysis completed. Results saved to database.\n";
  return 0;
}
