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
struct TradeRecord {
  std::string timestamp;
  std::string message_snippet;
  std::string topic;
  double sentiment_score;
  int signal; // 1 = Long, -1 = Short, 0 = Hold
  double gross_return;
  double net_return;
  double equity;
  double drawdown;
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

// Parses commas and multi-line fields in quotes on the CSV according to
// RFC-4180
std::vector<std::vector<std::string>> parse_csv(const std::string &filepath) {
  std::ifstream file(filepath, std::ios::binary);
  std::vector<std::vector<std::string>> records;
  if (!file.is_open()) {
    return records;
  }

  std::vector<std::string> current_record;
  std::string current_field;
  char c;
  bool inside_quotes = false;

  while (file.get(c)) {
    if (c == '"') {
      if (inside_quotes && file.peek() == '"') {
        current_field += '"';
        file.get(); // consume peeked quotation mark
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
    std::string h = header[i];
    h.erase(std::remove(h.begin(), h.end(), '\r'), h.end());
    h.erase(std::remove(h.begin(), h.end(), '\n'), h.end());
    h.erase(std::remove(h.begin(), h.end(), '"'), h.end());
    if (h == name)
      return i;
  }
  return -1;
}

// Cleans up a string by removing unecessary characters
std::string trim(const std::string &str) {
  std::string s = str;
  s.erase(std::remove(s.begin(), s.end(), '\r'), s.end());
  s.erase(std::remove(s.begin(), s.end(), '\n'), s.end());
  s.erase(std::remove(s.begin(), s.end(), '"'), s.end());
  size_t first = s.find_first_not_of(" \t");
  if (first == std::string::npos)
    return "";
  size_t last = s.find_last_not_of(" \t");
  return s.substr(first, (last - first + 1));
}

int main(int argc, char *argv[]) {
  std::string dataset_path = "data/final_dataset.csv";
  std::string topic_filter = "All";
  std::string asset = "ES";
  std::string horizon = "1d";
  double threshold = 0.05;
  double cost_bps = 5.0; // 5 basis points = 0.05% = 0.0005
  double initial_capital = 10000.0;
  bool reversal_mode = false;
  bool print_trades = false;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--dataset" && i + 1 < argc) {
      dataset_path = argv[++i];
    } else if (arg == "--topic" && i + 1 < argc) {
      topic_filter = argv[++i];
    } else if (arg == "--asset" && i + 1 < argc) {
      asset = argv[++i];
    } else if (arg == "--horizon" && i + 1 < argc) {
      horizon = argv[++i];
    } else if (arg == "--threshold" && i + 1 < argc) {
      threshold = std::stod(argv[++i]);
    } else if (arg == "--cost" && i + 1 < argc) {
      cost_bps = std::stod(argv[++i]);
    } else if (arg == "--capital" && i + 1 < argc) {
      initial_capital = std::stod(argv[++i]);
    } else if (arg == "--reversal") {
      reversal_mode = true;
    } else if (arg == "--print-trades") {
      print_trades = true;
    } else if (arg == "--help" || arg == "-h") {
      std::cout
          << "Usage: backtester.exe [options]\n"
          << "Options:\n"
          << "  --dataset <path>      Path to merged CSV (default: "
             "data/final_dataset.csv)\n"
          << "  --topic <topic>       Filter by topic or 'All' (default: All)\n"
          << "                        Topics: 'China', 'Federal politics', "
             "'Iran war/Oil',\n"
          << "                                'National security/Immigration', "
             "'Tariffs', 'Technology'\n"
          << "  --asset <name>        Asset to trade (default: ES)\n"
          << "                        Assets: 'ES', 'YM', 'I_NDX', 'CL', 'ZN', "
             "'X_BTCUSD'\n"
          << "  --horizon <time>      Holding horizon (default: 1d)\n"
          << "                        Horizons: '5m', '15m', '30m', '1h', "
             "'1d'\n"
          << "  --threshold <val>     Sentiment threshold to enter trade "
             "(default: 0.05)\n"
          << "  --cost <bps>          Transaction costs in basis points per "
             "trade (default: 5.0)\n"
          << "  --capital <val>       Starting balance (default: 10000.0)\n"
          << "  --reversal            Run in sentiment-reversal mode (short "
             "positive, long negative)\n"
          << "  --print-trades        Print trade details to stdout\n"
          << "  --help, -h            Show this help menu\n";
      return 0;
    }
  }

  std::cout << "==================================================\n";
  std::cout << "          TRUMP MARKET ANALYSIS BACKTESTER\n";
  std::cout << "==================================================\n";
  std::cout << "Dataset:          " << dataset_path << "\n";
  std::cout << "Target Asset:     " << asset << "\n";
  std::cout << "Holding Horizon:  " << horizon << "\n";
  std::cout << "Filter Topic:     " << topic_filter << "\n";
  std::cout << "Sentiment Thresh: " << threshold << "\n";
  std::cout << "Trans. Cost Bps:  " << cost_bps << " bps ("
            << (cost_bps / 10000.0) << ")\n";
  std::cout << "Starting Capital: $" << std::fixed << std::setprecision(2)
            << initial_capital << "\n";
  std::cout << "Strategy Mode:    "
            << (reversal_mode ? "Sentiment Reversal" : "Sentiment Directional")
            << "\n";
  std::cout << "==================================================\n\n";

  if (!fs::exists(dataset_path)) {
    std::cerr << "Error: Dataset file not found at " << dataset_path << "\n";
    return 1;
  }

  std::cout << "Parsing dataset...\n";
  auto records = parse_csv(dataset_path);
  if (records.empty()) {
    std::cerr << "Error: Empty dataset or failed parsing.\n";
    return 1;
  }
  std::cout << "Total rows parsed: " << records.size() << "\n";

  // Get column indices
  auto header = records[0];
  int ts_col = find_col(header, "timestamp_utc");
  int msg_col = find_col(header, "message_snippet");
  int topic_col = find_col(header, "topic");
  int sent_score_col = find_col(header, "sentiment_score");
  std::string return_col_name = "return_" + horizon + "_" + asset;
  int return_col = find_col(header, return_col_name);

  if (ts_col == -1)
    std::cerr << "[Warning] 'timestamp_utc' column not found.\n";
  if (msg_col == -1)
    std::cerr << "[Warning] 'message_snippet' column not found.\n";
  if (topic_col == -1)
    std::cerr << "[Warning] 'topic' column not found.\n";
  if (sent_score_col == -1)
    std::cerr << "[Warning] 'sentiment_score' column not found.\n";
  if (return_col == -1) {
    std::cerr << "Error: Target return column '" << return_col_name
              << "' not found in dataset.\n";
    return 1;
  }

  // Sort records chronologically (oldest to newest) by timestamp_utc
  if (ts_col != -1 && records.size() > 2) {
    std::sort(records.begin() + 1, records.end(), [ts_col](const std::vector<std::string> &a, const std::vector<std::string> &b) {
      if (a.size() <= (size_t)ts_col) return true;
      if (b.size() <= (size_t)ts_col) return false;
      return a[ts_col] < b[ts_col];
    });
  }

  double equity = initial_capital;
  double peak_equity = initial_capital;
  double max_drawdown = 0.0;
  long long first_timestamp_ms = -1;
  long long last_timestamp_ms = -1;

  std::vector<TradeRecord> trades;
  double cost_pct = cost_bps / 10000.0; // cost as a fraction of trade value

  for (size_t i = 1; i < records.size(); ++i) {
    const auto &row = records[i];
    if (row.size() <=
        (size_t)std::max({ts_col, topic_col, sent_score_col, return_col})) {
      continue;
    }

    std::string timestamp = row[ts_col];
    std::string topic = trim(row[topic_col]);
    std::string sent_str = row[sent_score_col];
    std::string ret_str = row[return_col];
    std::string snippet = (msg_col != -1) ? row[msg_col] : "";

    // Apply topic filter
    if (topic_filter != "All" && topic != topic_filter) {
      continue;
    }

    // Skip blank or invalid sentiment/returns
    if (sent_str.empty() || ret_str.empty() || ret_str == "NaN") {
      continue;
    }

    double sentiment = 0.0;
    double raw_return = 0.0;
    try {
      sentiment = std::stod(sent_str);
      raw_return = std::stod(ret_str);
    } catch (...) {
      continue;
    }

    // Generate Signal
    int signal = 0;
    if (sentiment > threshold) {
      signal = reversal_mode ? -1 : 1; // short if reversal_mode = true
    } else if (sentiment < -threshold) {
      signal = reversal_mode ? 1 : -1; // long if reversal_mode = true
    }

    if (signal == 0) {
      continue; // No trade
    }

    // Get first/last event timestamps to calculate annualized duration
    long long ts_ms = utc_to_ms(timestamp);
    if (ts_ms != -1) {
      if (first_timestamp_ms == -1)
        first_timestamp_ms = ts_ms;
      last_timestamp_ms = ts_ms;
    }

    // Trade execution
    double gross_return = raw_return * signal;
    double net_return = gross_return - cost_pct;

    equity = equity * (1.0 + net_return); // invest 100% of equity in each trade
    if (equity < 0.0)
      equity = 0.0; // avoid negative balance

    if (equity > peak_equity) {
      peak_equity = equity;
    }
    double current_drawdown = (peak_equity - equity) / peak_equity;
    if (current_drawdown > max_drawdown) {
      max_drawdown = current_drawdown;
    }

    TradeRecord trade;
    trade.timestamp = timestamp;
    trade.message_snippet = snippet;
    trade.topic = topic;
    trade.sentiment_score = sentiment;
    trade.signal = signal;
    trade.gross_return = gross_return;
    trade.net_return = net_return;
    trade.equity = equity;
    trade.drawdown = current_drawdown;

    trades.push_back(trade);
  }

  if (trades.empty()) {
    std::cout
        << "No trades were generated with the current parameter settings.\n";
    return 0;
  }

  // Calculate stats
  size_t total_trades = trades.size();
  size_t winning_trades = 0;
  double sum_net_returns = 0.0;
  std::vector<double> net_returns_list;

  for (const auto &t : trades) {
    if (t.net_return > 0.0) {
      winning_trades++;
    }
    sum_net_returns += t.net_return;
    net_returns_list.push_back(t.net_return);
  }

  double win_rate = (double)winning_trades / total_trades;
  double mean_return = sum_net_returns / total_trades;

  // Std dev of returns
  double variance = 0.0;
  for (double r : net_returns_list) {
    variance += (r - mean_return) * (r - mean_return);
  }
  double std_dev =
      (total_trades > 1) ? std::sqrt(variance / (total_trades - 1)) : 0.0;

  // Annualized calculations
  double total_years = 1.0;
  if (first_timestamp_ms != -1 && last_timestamp_ms != -1 &&
      last_timestamp_ms > first_timestamp_ms) {
    double total_days =
        (last_timestamp_ms - first_timestamp_ms) / (1000.0 * 60 * 60 * 24);
    total_years = total_days / 365.25;
    if (total_years < 0.01)
      total_years = 0.01; // Avoid division by zero or extreme stats
  }

  double total_return_pct = (equity - initial_capital) / initial_capital;

  // Compound annual growth rate of the capital over the duration of the
  // backtest
  double annualized_return_pct =
      std::pow(equity / initial_capital, 1.0 / total_years) - 1.0;

  // Annualized Sharpe Ratio
  // We can assume risk-free returns are 0 because this strategy supports
  // maximum one-day horizons. The risk-free return over a single-trade
  // timeframe is close to 0.
  double trades_per_year = (double)total_trades / total_years;
  double sharpe_ratio = 0.0;
  if (std_dev > 1e-8) {
    sharpe_ratio = (mean_return / std_dev) * std::sqrt(trades_per_year);
  }

  // Print results
  std::cout << "\n==================================================\n";
  std::cout << "                BACKTEST RESULTS\n";
  std::cout << "==================================================\n";
  std::cout << "Total Trades:       " << total_trades << "\n";
  std::cout << "Winning Trades:     " << winning_trades << "\n";
  std::cout << "Losing Trades:      " << (total_trades - winning_trades)
            << "\n";
  std::cout << "Win Rate:           " << std::fixed << std::setprecision(2)
            << (win_rate * 100.0) << "%\n";
  std::cout << "Initial Capital:    $" << std::fixed << std::setprecision(2)
            << initial_capital << "\n";
  std::cout << "Final Equity:       $" << std::fixed << std::setprecision(2)
            << equity << "\n";
  std::cout << "Total Profit/Loss:  $" << std::fixed << std::setprecision(2)
            << (equity - initial_capital) << " (" << std::fixed
            << std::setprecision(2) << (total_return_pct * 100.0) << "%)\n";
  std::cout << "Annualized Return:  " << std::fixed << std::setprecision(2)
            << (annualized_return_pct * 100.0) << "%\n";
  std::cout << "Max Drawdown:       " << std::fixed << std::setprecision(2)
            << (max_drawdown * 100.0) << "%\n";
  std::cout << "Sharpe Ratio:       " << std::fixed << std::setprecision(3)
            << sharpe_ratio << "\n";
  std::cout << "Trades/Year (Avg):  " << std::fixed << std::setprecision(1)
            << trades_per_year << "\n";
  std::cout << "==================================================\n\n";

  // Print detailed trades if flag enabled
  if (print_trades) {
    std::cout << "DETAILED TRADES LOG (First 20 / Last 20):\n";
    std::cout << std::left << std::setw(20) << "Timestamp" << std::setw(15)
              << "Topic" << std::right << std::setw(8) << "Score"
              << std::setw(8) << "Signal" << std::setw(12) << "Net Ret"
              << std::setw(12) << "Equity"
              << "   " << "Message Snippet" << "\n";
    std::cout << std::string(100, '-') << "\n";

    size_t display_count = 20;
    for (size_t idx = 0; idx < total_trades; ++idx) {
      if (total_trades > 2 * display_count && idx >= display_count &&
          idx < total_trades - display_count) {
        if (idx == display_count) {
          std::cout << "... [ " << (total_trades - 2 * display_count)
                    << " trades hidden ] ...\n";
        }
        continue;
      }
      const auto &t = trades[idx];
      std::cout << std::left << std::setw(20) << t.timestamp.substr(0, 19)
                << std::setw(15) << t.topic.substr(0, 14) << std::right
                << std::setw(8) << std::fixed << std::setprecision(3)
                << t.sentiment_score << std::setw(8)
                << (t.signal == 1 ? "LONG" : "SHORT") << std::setw(12)
                << std::fixed << std::setprecision(5) << t.net_return
                << std::setw(12) << std::fixed << std::setprecision(2)
                << t.equity << "   " << t.message_snippet << "\n";
    }
    std::cout << "==================================================\n\n";
  }

  // Save detailed trades to results folder
  std::string output_dir = "src/results/backtesting-results";
  if (!fs::exists("src") && fs::exists("backtester.cpp")) {
    output_dir = "../results/backtesting-results";
  }
  if (!fs::exists(output_dir)) {
    fs::create_directories(output_dir);
  }
  std::string clean_topic = topic_filter;
  std::replace(clean_topic.begin(), clean_topic.end(), '/', '_');
  std::string output_path =
      output_dir + "/backtest_trades_" + asset + "_" + clean_topic + "_" + horizon + (reversal_mode ? "_reversal" : "") + ".csv";
  std::ofstream out(output_path);
  if (out.is_open()) {
    out << "timestamp,message_snippet,topic,sentiment_score,signal,gross_"
           "return,net_return,equity,drawdown\n";
    for (const auto &t : trades) {
      std::string clean_snippet = t.message_snippet;
      clean_snippet.erase(
          std::remove(clean_snippet.begin(), clean_snippet.end(), '"'),
          clean_snippet.end());
      out << t.timestamp << ",\"" << clean_snippet << "\"," << t.topic << ","
          << t.sentiment_score << "," << t.signal << "," << t.gross_return
          << "," << t.net_return << "," << t.equity << "," << t.drawdown
          << "\n";
    }
    out.close();
    std::cout << "Detailed trade logs successfully written to " << output_path
              << "\n";
  } else {
    std::cerr << "[Warning] Could not open output path " << output_path
              << " for trade logs.\n";
  }

  return 0;
}
