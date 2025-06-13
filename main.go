package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"github.com/prometheus/client_golang/api"
	v1 "github.com/prometheus/client_golang/api/prometheus/v1"
	"github.com/prometheus/common/model"
	"io/ioutil"
	"log"
	"net/http"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Services          map[string]string `yaml:"services"`
	Token             string            `yaml:"token"`
	PrometheusQueries map[string]string `yaml:"prometheus_queries"`
	Containers        []string          `yaml:"containers"`
	WindowSize        int               `yaml:"window_size"`
}

type MetricPayload struct {
	Service   string                        `json:"service"`
	Timestamp time.Time                     `json:"timestamp"`
	Metrics   map[string]map[string]float64 `json:"metrics"`
}

var metricsWindow []MetricPayload

type authTransport struct {
	Token     string
	Transport http.RoundTripper
}

var serviceRoutes map[string]string

var prometheusQueries map[string]string

// Wakes up periodically to fetch and send metrics to LLM service
func main() {
	cfg, err := loadConfig("config.yaml")
	if err != nil {
		log.Fatalf("Failed to load config: %s", err)
	}

	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client, err := api.NewClient(api.Config{
		Address: cfg.Services["prometheus"],
		RoundTripper: &authTransport{
			Token:     cfg.Token,
			Transport: transport,
		},
	})

	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			payload := collectMetrics(client, cfg.PrometheusQueries, cfg.Containers)
			if len(metricsWindow) == cfg.WindowSize {
				// remove oldest metrics from window
				metricsWindow = metricsWindow[1:]
			}
			metricsWindow = append(metricsWindow, payload)

			if len(metricsWindow) == cfg.WindowSize {
				err := sendToLLMService(metricsWindow)
				if err != nil {
					log.Printf("Error sending to LLM service: %v", err)
				}
			}
		}
	}
}

func sendToLLMService(window []MetricPayload) error {
	body, err := json.Marshal(window)
	if err != nil {
		return err
	}

	resp, err := http.Post("http://localhost:8082/analyze", "application/json", bytes.NewReader(body))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		responseBody, _ := ioutil.ReadAll(resp.Body)
		return fmt.Errorf("LLM service error: %s", responseBody)
	}

	log.Println("Sent metrics to LLM service")
	return nil
}

func collectMetrics(client api.Client, queries map[string]string, containers []string) MetricPayload {
	v1api := v1.NewAPI(client)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	timestamp := time.Now()
	payload := MetricPayload{
		Timestamp: timestamp,
		Metrics:   make(map[string]map[string]float64),
	}

	for _, container := range containers {
		payload.Metrics[container] = make(map[string]float64)
		for baseMetric, template := range queries {
			query := fmt.Sprintf(template, container)
			result, _, err := v1api.Query(ctx, query, timestamp)
			if err != nil {
				log.Printf("Prometheus query error [%s]: %v", baseMetric, err)
				continue
			}

			if vector, ok := result.(model.Vector); ok && len(vector) > 0 {
				log.Printf("Prometheus query %s returned %v", query, vector[0].Value)
				payload.Metrics[container][baseMetric] = float64(vector[0].Value)
			}
		}
	}

	return payload
}

//func fetchAndSendPromMetrics(client api.Client, queries map[string]string, containers []string) {
//	v1api := v1.NewAPI(client)
//	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
//	defer cancel()
//
//	currentTime := time.Now()
//
//	for _, container := range containers {
//		for baseMetric, promTemplate := range queries {
//			query := fmt.Sprintf(promTemplate, container)
//			metricKey := fmt.Sprintf("%s-%s", container, baseMetric)
//
//			result, warnings, err := v1api.Query(ctx, query, currentTime)
//			if err != nil {
//				log.Printf("Error querying Prometheus for %s: %v", metricKey, err)
//				continue
//			}
//			if len(warnings) > 0 {
//				log.Printf("Warnings for query [%s]: %v", metricKey, warnings)
//			}
//
//			log.Printf("=== [%s] Query: %s ===", metricKey, query)
//
//			switch result.Type() {
//			case model.ValVector:
//				vector := result.(model.Vector)
//				for _, sample := range vector {
//					labels := sample.Metric
//					fmt.Printf("  %s %v = %v\n", metricKey, labels, sample.Value)
//				}
//			default:
//				log.Printf("Unhandled result type for %s: %v", metricKey, result.Type())
//			}
//		}
//	}
//}

func (t *authTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Bearer "+t.Token)
	return t.Transport.RoundTrip(req)
}

// Reads system config and important environment variables
func loadConfig(path string) (Config, error) {
	var cfg Config
	data, err := ioutil.ReadFile(path)
	if err != nil {
		return cfg, err
	}

	err = yaml.Unmarshal(data, &cfg)
	if err != nil {
		return cfg, err
	}

	return cfg, nil
}

// Queries service metrics, parses, and sends to Python/LLM service
//func fetchAndSendMetrics(service, url string) {
//	resp, err := http.Get(url)
//	if err != nil {
//		log.Printf("Error fetching metrics for %s: %v\n", service, err)
//		return
//	}
//	defer resp.Body.Close()
//
//	body, _ := ioutil.ReadAll(resp.Body)
//	parsedMetrics := parsePrometheusMetrics(string(body))
//
//	payload := MetricPayload{
//		Service:   service,
//		Timestamp: time.Now().UTC().Format(time.RFC3339),
//		Metrics:   parsedMetrics,
//	}
//
//	postToPythonLLM(payload)
//}
//
//func parsePrometheusMetrics(data string) map[string]float64 {
//	lines := strings.Split(data, "\n")
//	metrics := make(map[string]float64)
//
//	for _, line := range lines {
//		if strings.HasPrefix(line, "#") || line == "" {
//			continue
//		}
//		parts := strings.Fields(line)
//		if len(parts) != 2 {
//			continue
//		}
//		key := parts[0]
//		var value float64
//		fmt.Sscanf(parts[1], "%f", &value)
//		metrics[key] = value
//	}
//
//	return metrics
//}
//
//func postToPythonLLM(payload MetricPayload) {
//	jsonBytes, err := json.Marshal(payload)
//	if err != nil {
//		log.Println("Failed to marshal payload:", err)
//		return
//	}
//
//	resp, err := http.Post("http://localhost:8000/metrics", "application/json", bytes.NewBuffer(jsonBytes))
//	if err != nil {
//		log.Printf("Failed to POST metrics to Python LLM: %v\n", err)
//		return
//	}
//	defer resp.Body.Close()
//
//	log.Printf("Posted metrics for %s, response status: %s\n", payload.Service, resp.Status)
//}
