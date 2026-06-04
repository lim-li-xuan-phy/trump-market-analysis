#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
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
  // Array of no. of days in each month of a non-leap year
  static const int days_in_month[] = {31, 28, 31, 30, 31, 30,
                                      31, 31, 30, 31, 30, 31};

  // Count leap years since 1970
  int leap_days = 0;
  for (int y = 1970; y < year; ++y) {
    if ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0)) { // y is a leap year
      leap_days++;
    }
  }

  // Count no. of days since the start of `year`
  long long days = (year - 1970) * 365 + leap_days;
  for (int m = 0; m < month - 1; ++m) {
    if (m == 1 && ((year % 4 == 0 && year % 100 != 0) ||
                   (year % 400 == 0))) { // m is a leap-year February
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
  int year, month, day,
      hour = 0, min = 0,
      sec = 0; // if time is missing from ts_str, time defaults to 00:00:00
  if (sscanf(ts_str.c_str(), "%d-%d-%d %d:%d:%d", &year, &month, &day, &hour,
             &min, &sec) < 3) {
    return -1;
  }
  return timestamp_to_s(year, month, day, hour, min, sec) * 1000LL;
}

// Parses commas and multi-line fields in quotes on the CSV according to
// RFC-4180
std::vector<std::vector<std::string>> parse_csv(const std::string &filepath) {
  std::ifstream file(filepath, std::ios::binary);
  std::vector<std::vector<std::string>> records;
  if (!file.is_open()) {
    return records; // returns empty structure
  }

  std::vector<std::string> current_record;
  std::string current_field;
  char c;
  bool inside_quotes = false;

  while (file.get(c)) {
    if (c == '"') {
      if (inside_quotes && file.peek() == '"') {
        current_field += '"';
        file.get(); // consume the peeked quotation mark
      } else {
        inside_quotes = !inside_quotes;
      }
    } else if (c == ',' && !inside_quotes) {
      current_record.push_back(current_field);
      current_field.clear();
    } else if ((c == '\n' || c == '\r') && !inside_quotes) {
      if (c == '\r' && file.peek() == '\n') {
        file.get(); // consume \n
      }
      current_record.push_back(current_field);
      records.push_back(current_record);
      current_record.clear();
      current_field.clear();
    } else {
      current_field += c;
    }
  }
  if (!current_field.empty() || !current_record.empty()) {
    current_record.push_back(current_field);
    records.push_back(current_record);
  }
  return records;
}

// Finds a column index in the header row, by the column name
int find_col(const std::vector<std::string> &header, const std::string &name) {
  for (size_t i = 0; i < header.size(); ++i) {
    // Strip carriage returns or whitespace if any
    std::string h = header[i];
    h.erase(std::remove(h.begin(), h.end(), '\r'), h.end());
    h.erase(std::remove(h.begin(), h.end(), '\n'), h.end());
    if (h == name)
      return i;
  }
  return -1;
}

// Get a sorted list of the dates that have CSV files in the minute/<asset>/
// folder
std::vector<std::string> get_sorted_dates(const std::string &asset_dir) {
  std::vector<std::string> dates;
  if (!fs::exists(asset_dir))
    return dates;
  for (const auto &entry : fs::directory_iterator(asset_dir)) {
    if (entry.path().extension() == ".csv") {
      std::string filename = entry.path().stem().string();
      // Expected filename format: YYYY-MM-DD
      if (filename.size() == 10 && filename[4] == '-' && filename[7] == '-') {
        dates.push_back(filename);
      }
    }
  }
  std::sort(dates.begin(), dates.end()); // Sort dates from earliest to latest
  return dates;
}

// Load minute bars from a given CSV file
std::vector<MinuteBar> load_csv_bars(const std::string &filepath) {
  std::vector<MinuteBar> bars;
  auto records = parse_csv(filepath);
  if (records.empty())
    return bars;

  auto header = records[0];
  int ts_idx = find_col(header, "timestamp_ms");
  int open_idx = find_col(header, "open");
  int high_idx = find_col(header, "high");
  int low_idx = find_col(header, "low");
  int close_idx = find_col(header, "close");
  int vol_idx = find_col(header, "volume");

  if (ts_idx == -1 || open_idx == -1 || close_idx == -1) {
    return bars;
  }

  for (size_t i = 1; i < records.size(); ++i) {
    const auto &row = records[i];
    if (row.size() <= std::max({ts_idx, open_idx, close_idx}))
      continue;

    try {
      MinuteBar bar;
      bar.timestamp_ms = std::stoll(row[ts_idx]);
      bar.open = std::stod(row[open_idx]);
      bar.high = (high_idx != -1 && row.size() > (size_t)high_idx)
                     ? std::stod(row[high_idx])
                     : bar.open;
      bar.low = (low_idx != -1 && row.size() > (size_t)low_idx)
                    ? std::stod(row[low_idx])
                    : bar.open;
      bar.close = std::stod(row[close_idx]);
      bar.volume = (vol_idx != -1 && row.size() > (size_t)vol_idx)
                       ? std::stod(row[vol_idx])
                       : 0.0;
      bars.push_back(bar);
    } catch (...) {
      // Skip malformed rows
      continue;
    }
  }
  return bars;
}

// Load the asset's data for `post_date` and the next 2 available trading
// dates to handle weekends/holidays
std::vector<MinuteBar>
load_asset_data(const std::string &asset_dir,
                const std::vector<std::string> &sorted_dates,
                const std::string &post_date) {
  std::vector<MinuteBar> bars;

  // Find the first date in sorted_dates that is later than or the same as
  // post_date
  auto it =
      std::lower_bound(sorted_dates.begin(), sorted_dates.end(), post_date);
  if (it == sorted_dates.end()) {
    // No trading days found later than or the same as post_date
    return bars;
  }

  // Get the data from the relevant CSV files
  size_t count = 0;
  while (it != sorted_dates.end() && count < 3) {
    std::string filepath = asset_dir + "/" + *it + ".csv";
    auto day_bars = load_csv_bars(filepath); // All 1-min bars of a chosen date
    // Insert `day_bars` to the end of `bars`
    bars.insert(bars.end(), day_bars.begin(), day_bars.end());
    it++;
    count++;
  }

  // Sort and remove duplicates (just in case)
  std::sort(bars.begin(), bars.end(),
            [](const MinuteBar &a, const MinuteBar &b) {
              return a.timestamp_ms < b.timestamp_ms;
            });

  return bars;
}

// Find the closest price to a target timestamp. Can be before or after the
// target.
double find_price_at(const std::vector<MinuteBar> &bars, long long target_ms,
                     long long tolerance_ms, size_t &found_idx) {
  auto it = std::lower_bound(bars.begin(), bars.end(), target_ms,
                             [](const MinuteBar &bar, long long val) {
                               // A MinuteBar is considered "less than" the
                               // search value if its timestamp is smaller
                               // than the target timestamp
                               return bar.timestamp_ms < val;
                             });

  if (it == bars.end()) { // all bars in `bars` are earlier than `target_ms`
    if (!bars.empty()) {
      auto last_it = std::prev(bars.end()); // the latest bar in `bars`
      long long diff = std::abs(last_it->timestamp_ms - target_ms);
      if (diff <=
          tolerance_ms) { // latest bar is within `tolerance_ms` of `target_ms`
        found_idx =
            std::distance(bars.begin(), last_it); // index of the latest bar
        return last_it->close;                    // close price of latest bar
      }
    }
    return -1.0; // No suitable price found
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
  return -1.0; // No suitable bars found
}

// Calculate volatility of a stock's returns over a given time window.
// Volatility = standard deviation of 1-minute returns / sqrt(number of 1-minute
// periods in the window)
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

// Calculate Beta of a given asset relative to market benchmark.
// Time window of the asset and the benchmark must be the same for beta
// calculation.
double compute_beta(const std::vector<MinuteBar> &asset_bars,
                    size_t asset_start_idx, size_t asset_end_idx,
                    const std::vector<MinuteBar> &bench_bars) {
  if (asset_end_idx <= asset_start_idx || asset_end_idx >= asset_bars.size())
    return -99.0;

  long long t_start = asset_bars[asset_start_idx].timestamp_ms;
  long long t_end = asset_bars[asset_end_idx].timestamp_ms;

  // The first benchmark bar that is >= t_start
  auto bench_start_it =
      std::lower_bound(bench_bars.begin(), bench_bars.end(), t_start,
                       [](const MinuteBar &bar, long long val) {
                         return bar.timestamp_ms < val;
                       });
  // The last benchmark bar that is <= t_end
  auto bench_end_it =
      std::lower_bound(bench_bars.begin(), bench_bars.end(), t_end,
                       [](const MinuteBar &bar, long long val) {
                         return bar.timestamp_ms < val;
                       });

  // Error if benchmark data starts after asset data
  if (bench_start_it == bench_bars.end())
    return -99.0;

  // Create map of timestamp -> close for asset bars in the time window
  std::unordered_map<long long, double> asset_closes;
  for (size_t i = asset_start_idx; i <= asset_end_idx; ++i) {
    asset_closes[asset_bars[i].timestamp_ms] = asset_bars[i].close;
  }

  std::vector<std::pair<double, double>>
      aligned_returns; // (asset_return, bench_return)

  // Iterate through all benchmark bars within the time window
  for (auto it = bench_start_it; it != bench_end_it && it != bench_bars.end();
       ++it) {
    if (it == bench_bars.begin())
      continue;
    auto prev_it = std::prev(it);

    long long t_curr = it->timestamp_ms;
    long long t_prev = prev_it->timestamp_ms;

    // Ensure consecutive minute bars (max 65 seconds gap)
    if (t_curr - t_prev > 65000)
      continue;

    // If the current and previous timestamps from the benchmark data are
    // present in the asset data, add the corresponding asset and benchmark
    // returns to `aligned_returns`
    if (asset_closes.count(t_curr) && asset_closes.count(t_prev)) {
      double prev_asset_price = asset_closes[t_prev];
      double prev_bench_price = prev_it->close;
      // Ensure we don't divide by zero
      if (prev_asset_price > 0.0 && prev_bench_price > 0.0) {
        double asset_ret =
            (asset_closes[t_curr] - prev_asset_price) / prev_asset_price;
        double bench_ret = (it->close - prev_bench_price) / prev_bench_price;
        aligned_returns.push_back({asset_ret, bench_ret});
      }
    }
  }

  if (aligned_returns.size() < 2)
    return -99.0; // Not enough overlapping bars to calculate beta

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

  if (var_bench == 0.0)
    return 0.0;
  return cov / var_bench;
}

int main(int argc, char *argv[]) {
  // argc: number of argument strings in the command, including program name.
  // argv: an array of pointers to each argument string in the command.
  std::string data_dir = "data";
  std::string output_path = "data/event_study_results.csv";
  std::string benchmark_asset = "ES";
  bool test_mode = false;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--data-dir" && i + 1 < argc) {
      data_dir = argv[++i];
    } else if (arg == "--output" && i + 1 < argc) {
      output_path = argv[++i];
    } else if (arg == "--benchmark" && i + 1 < argc) {
      benchmark_asset = argv[++i];
    } else if (arg == "--test") {
      test_mode = true;
    } else if (arg == "--help" || arg == "-h") {
      std::cout
          << "Usage: event_engine.exe [options]\n"
          << "Options:\n"
          << "  --data-dir <path>     Path to data directory (default: data)\n"
          << "  --output <path>       Path to output CSV (default: "
             "data/event_study_results.csv)\n"
          << "  --benchmark <asset>   Market benchmark asset name (default: "
             "ES)\n"
          << "  --test                Run in test mode (limits to first 50 "
             "posts)\n";
      return 0;
    }
  }

  std::cout << "Starting Event Study Calculation...\n";
  std::cout << "Data Dir: " << data_dir << "\n";
  std::cout << "Output Path: " << output_path << "\n";
  std::cout << "Benchmark Asset: " << benchmark_asset << "\n";
  std::cout << "Test Mode: "
            << (test_mode ? "Enabled (First 50 posts)" : "Disabled") << "\n\n";

  std::string posts_file = data_dir + "/trump_posts.csv";
  if (!fs::exists(posts_file)) {
    std::cerr << "Error: Posts file not found at " << posts_file << "\n";
    return 1;
  }

  // Parse Trump posts
  std::cout << "Parsing Trump posts...\n";
  auto post_records = parse_csv(posts_file);
  if (post_records.empty()) {
    std::cerr << "Error: No posts parsed.\n";
    return 1;
  }

  auto post_header = post_records[0];
  int ts_col = find_col(post_header, "timestamp_utc");
  int msg_col = find_col(post_header, "message");
  int url_col = find_col(post_header, "source_url");
  int type_col = find_col(post_header, "source_type");

  if (ts_col == -1 || msg_col == -1) {
    std::cerr << "Error: Required columns in trump_posts.csv not found.\n";
    return 1;
  }

  std::vector<TrumpPost> posts;
  for (size_t i = 1; i < post_records.size(); ++i) {
    const auto &row = post_records[i];
    if (row.size() <= std::max(ts_col, msg_col))
      continue;

    TrumpPost p;
    p.timestamp_utc = row[ts_col];
    p.timestamp_ms = utc_to_ms(p.timestamp_utc);
    if (p.timestamp_ms == -1)
      continue;
    p.message = row[msg_col];
    p.source_url =
        (url_col != -1 && row.size() > (size_t)url_col) ? row[url_col] : "";
    p.source_type =
        (type_col != -1 && row.size() > (size_t)type_col) ? row[type_col] : "";
    posts.push_back(p);
  }

  std::cout << "Loaded " << posts.size() << " valid posts.\n";

  // Sort posts chronologically first
  std::sort(posts.begin(), posts.end(),
            [](const TrumpPost &a, const TrumpPost &b) {
              return a.timestamp_ms < b.timestamp_ms;
            });

  if (test_mode) {
    if (posts.size() > 50) {
      posts.resize(50);
    }
    std::cout << "Trimmed to first " << posts.size()
              << " posts for test mode.\n";
  }

  std::cout << "First 5 sorted posts:\n";
  for (size_t i = 0; i < std::min((size_t)5, posts.size()); ++i) {
    std::cout << "  Post " << i << ": " << posts[i].timestamp_utc
              << " (ms=" << posts[i].timestamp_ms << ")\n";
  }

  // Asset list
  std::vector<std::string> assets = {"I_NDX", "X_BTCUSD", "CL",
                                     "ES",    "YM",       "ZN"};

  // Pre-load sorted dates for all assets from existing raw data files to
  // speed up lookups
  std::map<std::string, std::vector<std::string>> asset_sorted_dates;
  for (const auto &asset : assets) {
    std::string asset_dir = data_dir + "/market/minute/" + asset;
    asset_sorted_dates[asset] = get_sorted_dates(asset_dir);
    std::cout << "Asset: " << asset << " has "
              << asset_sorted_dates[asset].size() << " 1-min data files.\n";
  }

  // Output file preparation
  // Clear any existing data in the file at `output_path`.
  std::ofstream out(output_path);
  if (!out.is_open()) {
    std::cerr << "Error: Could not open output file " << output_path << "\n";
    return 1;
  }

  // Header row
  out << "timestamp_utc,message_snippet,asset,baseline_price,baseline_time_"
         "offset_sec"
      << ",return_1m,return_5m,return_15m,return_30m,return_1h,return_1d"
      << ",vol_1m,vol_5m,vol_15m,vol_30m,vol_1h,vol_1d"
      << ",beta_1m,beta_5m,beta_15m,beta_30m,beta_1h,beta_1d\n";

  // Event Study Windows (1m, 5m, 15m, 30m, 1h, 1d)
  const int num_windows = 6;
  std::string window_names[num_windows] = {"1m",  "5m", "15m",
                                           "30m", "1h", "1d"};
  long long window_ms[num_windows] = {
      60 * 1000LL,          // 1 min
      5 * 60 * 1000LL,      // 5 min
      15 * 60 * 1000LL,     // 15 min
      30 * 60 * 1000LL,     // 30 min
      60 * 60 * 1000LL,     // 1 hour
      24 * 60 * 60 * 1000LL // 1 day (24 hours)
  };

  long long window_tolerance_ms[num_windows] = {
      30 * 1000LL,     // 1m: 30 sec tolerance
      60 * 1000LL,     // 5m: 1 min tolerance
      2 * 60 * 1000LL, // 15m: 2 min tolerance
      3 * 60 * 1000LL, // 30m: 3 min tolerance
      5 * 60 * 1000LL, // 1h: 5 min tolerance
      30 * 60 * 1000LL // 1d: 30 min tolerance
  };

  // Process posts
  size_t processed_count = 0;
  auto start_time = std::chrono::high_resolution_clock::now();

  for (size_t post_idx = 0; post_idx < posts.size(); ++post_idx) {
    const auto &post = posts[post_idx];
    std::string post_date = post.timestamp_utc.substr(0, 10);

    // Load benchmark data (ES) for this post
    std::string bench_dir = data_dir + "/market/minute/" + benchmark_asset;
    auto bench_bars = load_asset_data(
        bench_dir, asset_sorted_dates[benchmark_asset], post_date);

    // Load all assets' data for this post
    for (const auto &asset : assets) {
      std::string asset_dir = data_dir + "/market/minute/" + asset;
      auto asset_bars =
          load_asset_data(asset_dir, asset_sorted_dates[asset], post_date);

      if (asset_bars.empty())
        continue;

      // Find baseline bar at or after post's timestamp
      size_t start_idx = 0;
      // Entry price, p0, is the nearest close price within 15 min tolerance of
      // the post's timestamp.
      double p0 = find_price_at(asset_bars, post.timestamp_ms, 15 * 60 * 1000LL,
                                start_idx);

      // Print first 5 posts to verify that raw data has been read properly
      if (post_idx < 5) {
        std::cout << "[DEBUG] Post index " << post_idx << " ("
                  << post.timestamp_utc << ", ms=" << post.timestamp_ms
                  << ") for asset " << asset << ": loaded " << asset_bars.size()
                  << " bars. p0=" << p0;
        if (!asset_bars.empty()) {
          std::cout << ", first_bar=" << asset_bars[0].timestamp_ms
                    << ", last_bar=" << asset_bars.back().timestamp_ms;
        }
        std::cout << "\n";
      }

      if (p0 <= 0.0) {
        // Asset was not active / no data around post time, skip
        continue;
      }

      long long t0 = asset_bars[start_idx].timestamp_ms;
      double baseline_offset_sec = (t0 - post.timestamp_ms) / 1000.0;

      double returns[num_windows] = {-1.0, -1.0, -1.0, -1.0, -1.0, -1.0};
      double vols[num_windows] = {-1.0, -1.0, -1.0, -1.0, -1.0, -1.0};
      double betas[num_windows] = {-99.0, -99.0, -99.0, -99.0, -99.0, -99.0};

      for (int w = 0; w < num_windows; ++w) {
        long long target_ms = t0 + window_ms[w];
        size_t end_idx = 0;
        double p_target = find_price_at(asset_bars, target_ms,
                                        window_tolerance_ms[w], end_idx);

        if (p_target > 0.0 && p0 > 0.0) {
          returns[w] = (p_target - p0) / p0;
          vols[w] = compute_volatility(asset_bars, start_idx, end_idx);

          if (asset == benchmark_asset) {
            betas[w] =
                1.0; // Self-beta is mathematically 1.0. No need to calculate.
          } else if (!bench_bars.empty()) {
            betas[w] = compute_beta(asset_bars, start_idx, end_idx, bench_bars);
          }
        }
      }

      // Write to output CSV
      // Keep a short snippet of the original post message to keep CSV clean
      std::string msg_snippet = post.message;
      // Clean message text of newlines, carriage returns, and quotes
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

      out << post.timestamp_utc << ",\"" << msg_snippet << "\"," << asset << ","
          << std::fixed << std::setprecision(6) << p0 << ","
          << baseline_offset_sec;

      // Write Returns
      for (int w = 0; w < num_windows; ++w) {
        if (returns[w] == -1.0 && vols[w] == -1.0) {
          out << ",NaN";
        } else {
          out << "," << returns[w];
        }
      }

      // Write Volatilities
      for (int w = 0; w < num_windows; ++w) {
        if (vols[w] == -1.0) {
          out << ",NaN";
        } else {
          out << "," << vols[w];
        }
      }

      // Write Betas
      for (int w = 0; w < num_windows; ++w) {
        if (betas[w] == -99.0) {
          out << ",NaN";
        } else {
          out << "," << betas[w];
        }
      }
      out << "\n";
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

  out.close();
  std::cout
      << "\nEvent study analysis completed successfully. Results saved to "
      << output_path << "\n";
  return 0;
}
