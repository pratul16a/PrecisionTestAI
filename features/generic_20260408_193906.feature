```gherkin
@automated @generic
Feature: Client Management
  As a user of the PrecisionTest application
  I want to navigate to the Clients section and filter by region
  So that I can view clients from specific geographical areas

  @client-filtering
  Scenario Outline: Filter clients by region
    Given I navigate to "<url>"
    When I click on "<section>"
    And I select "<region>" from "<dropdown>"
    Then I should see clients filtered by the selected region

    Examples:
      | url                   | section | region | dropdown |
      | http://localhost:3000 | Clients | Amer   | region   |
```