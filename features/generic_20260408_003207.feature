```gherkin
@automated @generic
Feature: Website Navigation and Element Visibility
  As a user
  I want to navigate to websites and verify element visibility
  So that I can ensure the application displays content correctly

  @smoke @navigation
  Scenario Outline: Verify element visibility after navigation
    Given I navigate to "<url>"
    Then I should see "<element>" visible

    Examples:
      | url                    | element |
      | https://example.com    |         |
```