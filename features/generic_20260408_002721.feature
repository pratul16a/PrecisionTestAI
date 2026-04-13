```gherkin
@automated @generic
Feature: E-commerce Website Navigation
  As a user
  I want to navigate to the e-commerce website
  So that I can access the online store

  @smoke @navigation
  Scenario Outline: Navigate to e-commerce website
    Given I am on a web browser
    When I navigate to "<url>"
    Then I should successfully reach the website
    And the page should load completely

    Examples:
      | url                           |
      | https://example-ecommerce.com |
```