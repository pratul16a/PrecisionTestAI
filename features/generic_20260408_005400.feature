```gherkin
@automated @generic
Feature: Basic Website Navigation
  As a user
  I want to navigate to a website
  So that I can verify basic page loading functionality

  @smoke @navigation
  Scenario Outline: Navigate to website and verify basic functionality
    Given I navigate to "<url>"
    Then I should see "<expected_content>"
    And I close the browser

    Examples:
      | url                    | expected_content |
      | https://example.com    |                  |
```